"""OAuth connect flow + token lifecycle for per-tenant sender mailboxes.

Responsibilities:

* **Initiate** — build a signed ``state`` and the provider consent URL.
* **Callback** — verify ``state``, exchange the code, verify the mailbox, store
  tokens *encrypted*, and activate the account (never activate an unverified box).
* **Token lifecycle** — hand out valid credentials for sending, refreshing when
  expired; on a revoked/expired refresh token, halt the account's campaigns,
  mark it ``needs_reauth`` and notify the factory — never fail silently.

The signed ``state`` carries the factory identity through the redirect, so the
callback needs no session cookie (the browser returns from Google/Microsoft).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import TokenDecryptError, decrypt, encrypt
from app.logging import get_logger
from app.models import (
    Campaign,
    CampaignStatus,
    Factory,
    SenderAccount,
    SenderProviderType,
    SenderVerificationStatus,
    User,
    utcnow,
)
from app.providers.base import (
    MailboxCredentials,
    MailboxVerificationError,
    TokenRefreshError,
)
from app.providers.registry import get_mailbox_provider
from app.services import audit, notifications

log = get_logger(__name__)

_ALGO = "HS256"
_STATE_PURPOSE = "mailbox_connect"
#: Marker on ``Campaign.paused_reason`` so campaigns paused by a reauth can be
#: automatically resumed when the mailbox is reconnected.
REAUTH_PAUSE_REASON = "Sender mailbox needs reconnection"
#: Refresh a little before actual expiry to avoid mid-send 401s.
_EXPIRY_SKEW = timedelta(seconds=60)


class OAuthStateError(Exception):
    """The returned ``state`` was missing, tampered with, or expired."""


class ReauthRequired(Exception):
    """A mailbox can no longer send and must be reconnected by the factory."""


class ConnectError(Exception):
    """A mailbox could not be connected/verified during the callback."""


# -- state ----------------------------------------------------------------


def _redirect_uri(provider_type: str) -> str:
    settings = get_settings()
    base = (settings.oauth_redirect_base_url or settings.api_base_url).rstrip("/")
    return f"{base}/api/v1/sender-accounts/callback/{provider_type}"


def _sign_state(
    *,
    factory_id: uuid.UUID,
    provider_type: str,
    user_id: uuid.UUID | None,
    account_id: uuid.UUID | None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "purpose": _STATE_PURPOSE,
        "factory_id": str(factory_id),
        "provider_type": provider_type,
        "user_id": str(user_id) if user_id else None,
        "account_id": str(account_id) if account_id else None,
        "nonce": secrets.token_urlsafe(8),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.oauth_state_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGO)


def _verify_state(state: str, provider_type: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[_ALGO])
    except jwt.PyJWTError as exc:
        raise OAuthStateError("invalid or expired OAuth state") from exc
    if payload.get("purpose") != _STATE_PURPOSE:
        raise OAuthStateError("unexpected OAuth state purpose")
    if payload.get("provider_type") != provider_type:
        raise OAuthStateError("OAuth state provider mismatch")
    return payload


# -- initiate -------------------------------------------------------------


def initiate_connect(
    db: Session,
    *,
    factory: Factory,
    provider_type: str,
    user: User,
    account: SenderAccount | None = None,
) -> str:
    """Return the provider consent URL to redirect the browser to."""
    _validate_provider(provider_type)
    provider = get_mailbox_provider(provider_type)
    state = _sign_state(
        factory_id=factory.id,
        provider_type=provider_type,
        user_id=user.id,
        account_id=account.id if account else None,
    )
    # For reconnect keep the same mailbox; for a fresh connect give the mock a
    # deterministic, plausible address (real providers ignore the hint).
    login_hint = (
        account.email
        if account
        else (
            factory.contact_email
            or f"{provider_type}.sender@{factory.sending_domain or 'mailbox.example'}"
        )
    )
    url = provider.authorization_url(
        state=state, redirect_uri=_redirect_uri(provider_type), login_hint=login_hint
    )
    audit.record(
        db,
        action="sender_connect_initiated",
        entity_type="sender_account",
        entity_id=account.id if account else None,
        actor=user,
        factory_id=factory.id,
        payload={"provider_type": provider_type, "reconnect": account is not None},
    )
    return url


# -- callback -------------------------------------------------------------


def complete_callback(db: Session, *, provider_type: str, code: str, state: str) -> SenderAccount:
    """Exchange the code, verify the mailbox, and activate the account."""
    _validate_provider(provider_type)
    payload = _verify_state(state, provider_type)
    factory_id = uuid.UUID(payload["factory_id"])
    user_id = uuid.UUID(payload["user_id"]) if payload.get("user_id") else None
    provider = get_mailbox_provider(provider_type)
    redirect_uri = _redirect_uri(provider_type)

    tokens = provider.exchange_code(code=code, redirect_uri=redirect_uri)

    # Verify the mailbox BEFORE activation — never trust the address unverified.
    # Real providers read the address from the profile; the mock recovers it from
    # the token it minted, so an empty hint here is fine.
    creds = MailboxCredentials(
        email="",
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_expires_at=tokens.expires_at,
    )
    try:
        identity = provider.verify_mailbox(creds)
    except MailboxVerificationError as exc:
        raise ConnectError(str(exc)) from exc

    account = _upsert_account(
        db,
        factory_id=factory_id,
        provider_type=provider_type,
        email=identity.email,
        provider_account_id=identity.provider_account_id,
        display_name=identity.display_name,
    )
    account.access_token_encrypted = encrypt(tokens.access_token)
    if tokens.refresh_token is not None:
        account.refresh_token_encrypted = encrypt(tokens.refresh_token)
    account.token_expires_at = tokens.expires_at
    account.scopes = tokens.scopes or provider.scopes
    account.verification_status = SenderVerificationStatus.verified
    account.verified_at = utcnow()
    account.reauth_reason = None
    if account.warmup_started_at is None:
        account.warmup_started_at = utcnow()
    db.flush()

    _resume_reauth_paused_campaigns(db, account)

    actor = db.get(User, user_id) if user_id else None
    audit.record(
        db,
        action="sender_connected",
        entity_type="sender_account",
        entity_id=account.id,
        actor=actor,
        actor_label=None if actor else "system",
        factory_id=factory_id,
        payload={"provider_type": provider_type, "email": identity.email},
    )
    notifications.notify(
        db,
        factory_id=factory_id,
        kind="mailbox_connected",
        title="Mailbox connected",
        body=f"{identity.email} is connected and verified for sending.",
        entity_type="sender_account",
        entity_id=account.id,
        user_id=user_id,
    )
    log.info("sender_connected", account_id=str(account.id), provider_type=provider_type)
    return account


def _upsert_account(
    db: Session,
    *,
    factory_id: uuid.UUID,
    provider_type: str,
    email: str,
    provider_account_id: str | None,
    display_name: str | None,
) -> SenderAccount:
    existing = db.scalar(
        select(SenderAccount).where(
            SenderAccount.factory_id == factory_id,
            SenderAccount.email == email,
            SenderAccount.provider_type == SenderProviderType(provider_type),
        )
    )
    if existing is not None:
        existing.provider_account_id = provider_account_id
        existing.display_name = display_name
        return existing
    account = SenderAccount(
        factory_id=factory_id,
        email=email,
        provider_type=SenderProviderType(provider_type),
        provider_account_id=provider_account_id,
        display_name=display_name,
        daily_send_limit=get_settings().sender_default_daily_limit,
    )
    db.add(account)
    db.flush()
    return account


# -- token lifecycle / reauth ---------------------------------------------


def ensure_valid_credentials(db: Session, account: SenderAccount) -> MailboxCredentials:
    """Return usable credentials for ``account``, refreshing if needed.

    On a revoked/expired refresh token this pauses the account's campaigns, marks
    it ``needs_reauth``, notifies the factory, and raises ``ReauthRequired``.
    """
    if account.verification_status == SenderVerificationStatus.needs_reauth:
        raise ReauthRequired("mailbox already flagged for reconnection")

    try:
        access_token = decrypt(account.access_token_encrypted)
        refresh_token = decrypt(account.refresh_token_encrypted)
    except TokenDecryptError as exc:
        mark_needs_reauth(db, account, reason="Stored credentials are unreadable")
        raise ReauthRequired("stored credentials unreadable") from exc

    if not _is_expired(account) and access_token:
        return MailboxCredentials(
            email=account.email,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=account.token_expires_at,
        )

    # Access token missing/expired — refresh it.
    if not refresh_token:
        mark_needs_reauth(db, account, reason="No refresh token on file")
        raise ReauthRequired("no refresh token")

    provider = get_mailbox_provider(account.provider_type.value)
    try:
        tokens = provider.refresh(refresh_token=refresh_token)
    except TokenRefreshError as exc:
        mark_needs_reauth(db, account, reason="Access could not be renewed (revoked or expired)")
        raise ReauthRequired(str(exc)) from exc

    account.access_token_encrypted = encrypt(tokens.access_token)
    if tokens.refresh_token is not None:
        account.refresh_token_encrypted = encrypt(tokens.refresh_token)
    account.token_expires_at = tokens.expires_at
    db.flush()
    return MailboxCredentials(
        email=account.email,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token or refresh_token,
        token_expires_at=tokens.expires_at,
    )


def mark_needs_reauth(db: Session, account: SenderAccount, *, reason: str) -> None:
    """Halt an account: pause its campaigns, flag reauth, notify — atomically.

    Idempotent: re-flagging an already-flagged account is a no-op beyond keeping
    the latest reason.
    """
    already = account.verification_status == SenderVerificationStatus.needs_reauth
    account.verification_status = SenderVerificationStatus.needs_reauth
    account.reauth_reason = reason
    db.flush()

    paused = _pause_account_campaigns(db, account)

    audit.record(
        db,
        action="sender_needs_reauth",
        entity_type="sender_account",
        entity_id=account.id,
        actor_label="system",
        factory_id=account.factory_id,
        payload={"reason": reason, "campaigns_paused": paused, "email": account.email},
    )
    if not already:
        notifications.notify(
            db,
            factory_id=account.factory_id,
            kind="mailbox_needs_reauth",
            title="Reconnect your mailbox",
            body=(
                f"Sending from {account.email} is paused: {reason}. "
                "Reconnect the mailbox to resume your campaigns."
            ),
            entity_type="sender_account",
            entity_id=account.id,
        )
    log.warning(
        "sender_needs_reauth",
        account_id=str(account.id),
        reason=reason,
        campaigns_paused=paused,
    )


def _pause_account_campaigns(db: Session, account: SenderAccount) -> int:
    """Pause the account's live campaigns so nothing tries to send while broken."""
    live = db.scalars(
        select(Campaign).where(
            Campaign.sender_account_id == account.id,
            Campaign.status.in_((CampaignStatus.active, CampaignStatus.draft)),
        )
    ).all()
    count = 0
    for campaign in live:
        campaign.status = CampaignStatus.paused
        campaign.paused_reason = REAUTH_PAUSE_REASON
        count += 1
    if count:
        db.flush()
    return count


def _resume_reauth_paused_campaigns(db: Session, account: SenderAccount) -> int:
    """On reconnect, reactivate exactly the campaigns a reauth had paused."""
    paused = db.scalars(
        select(Campaign).where(
            Campaign.sender_account_id == account.id,
            Campaign.status == CampaignStatus.paused,
            Campaign.paused_reason == REAUTH_PAUSE_REASON,
        )
    ).all()
    for campaign in paused:
        campaign.status = CampaignStatus.active
        campaign.paused_reason = None
    if paused:
        db.flush()
    return len(paused)


# -- helpers --------------------------------------------------------------


def _validate_provider(provider_type: str) -> None:
    try:
        SenderProviderType(provider_type)
    except ValueError as exc:
        raise ConnectError(f"unknown mailbox provider: {provider_type}") from exc


def _is_expired(account: SenderAccount) -> bool:
    if account.token_expires_at is None:
        return True
    return datetime.now(UTC) >= account.token_expires_at - _EXPIRY_SKEW

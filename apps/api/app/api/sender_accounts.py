"""Sender mailbox connection: OAuth connect/callback and account management.

A factory connects its own Gmail / Microsoft mailbox here. The initiate endpoints
return a provider consent URL; the browser is redirected there, then bounced back
to ``/callback/{provider}`` which exchanges the code, verifies the mailbox, stores
tokens encrypted, and returns the browser to the frontend onboarding page.

Every account query is scoped by ``factory_id`` (tenant isolation) via
``resolve_factory`` / ``get_owned_sender_account``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse, Response

from app.api.deps import DbDep, get_owned_sender_account, resolve_factory
from app.config import get_settings
from app.logging import get_logger
from app.models import SenderAccount, SenderProviderType, SenderVerificationStatus
from app.schemas.sender import ConnectResponse, SenderAccountOut
from app.security import CurrentUser
from app.services import audit, sender_accounts, sender_oauth

log = get_logger(__name__)

router = APIRouter(prefix="/sender-accounts", tags=["sender-accounts"])

_CONNECTABLE = {SenderProviderType.gmail.value, SenderProviderType.microsoft.value}


@router.get("", response_model=list[SenderAccountOut])
def list_accounts(db: DbDep, user: CurrentUser) -> list[SenderAccountOut]:
    factory = resolve_factory(db, user)
    rows = sender_accounts.list_for_factory(db, factory.id)
    return [SenderAccountOut.model_validate(r) for r in rows]


@router.post("/connect/{provider}", response_model=ConnectResponse)
def connect(provider: str, db: DbDep, user: CurrentUser) -> ConnectResponse:
    """Begin connecting a new mailbox; returns the provider consent URL."""
    if provider not in _CONNECTABLE:
        raise HTTPException(status_code=400, detail="Unsupported mailbox provider")
    factory = resolve_factory(db, user)
    url = sender_oauth.initiate_connect(db, factory=factory, provider_type=provider, user=user)
    db.commit()
    return ConnectResponse(authorization_url=url)


@router.post("/{account_id}/reconnect", response_model=ConnectResponse)
def reconnect(
    db: DbDep,
    user: CurrentUser,
    account: SenderAccount = Depends(get_owned_sender_account),
) -> ConnectResponse:
    """Re-run the consent flow for an existing (e.g. needs_reauth) mailbox."""
    factory = resolve_factory(db, user)
    url = sender_oauth.initiate_connect(
        db,
        factory=factory,
        provider_type=account.provider_type.value,
        user=user,
        account=account,
    )
    db.commit()
    return ConnectResponse(authorization_url=url)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(
    db: DbDep,
    user: CurrentUser,
    account: SenderAccount = Depends(get_owned_sender_account),
) -> Response:
    """Disconnect a mailbox: disable it and wipe its stored tokens."""
    account.verification_status = SenderVerificationStatus.disabled
    account.access_token_encrypted = None
    account.refresh_token_encrypted = None
    account.token_expires_at = None
    db.flush()
    audit.record(
        db,
        action="sender_disconnected",
        entity_type="sender_account",
        entity_id=account.id,
        actor=user,
        factory_id=account.factory_id,
        payload={"email": account.email},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/callback/{provider}")
def callback(
    provider: str,
    db: DbDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """OAuth redirect target. No auth — identity travels in the signed ``state``."""
    settings = get_settings()
    base = f"{settings.app_base_url.rstrip('/')}{settings.oauth_post_connect_path}"

    if error:
        log.info("oauth_callback_error", provider=provider, error=error)
        return RedirectResponse(url=f"{base}?error={error}", status_code=302)
    if not code or not state:
        return RedirectResponse(url=f"{base}?error=missing_code", status_code=302)

    try:
        account = sender_oauth.complete_callback(db, provider_type=provider, code=code, state=state)
        db.commit()
    except sender_oauth.OAuthStateError:
        db.rollback()
        return RedirectResponse(url=f"{base}?error=invalid_state", status_code=302)
    except sender_oauth.ConnectError as exc:
        db.rollback()
        log.warning("oauth_connect_failed", provider=provider, error=str(exc))
        return RedirectResponse(url=f"{base}?error=connect_failed", status_code=302)

    return RedirectResponse(url=f"{base}?connected=1&email={account.email}", status_code=302)

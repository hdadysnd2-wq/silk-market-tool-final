"""Sender mailbox connection: OAuth connect/callback and account management.

A factory connects its own Gmail / Microsoft mailbox here. The initiate endpoints
return a provider consent URL; the browser is redirected there, then bounced back
to ``/callback/{provider}`` which exchanges the code, verifies the mailbox, stores
tokens encrypted, and returns the browser to the frontend onboarding page.

Every account query is scoped by ``factory_id`` (tenant isolation) via
``resolve_factory`` / ``get_owned_sender_account``.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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

#: HttpOnly cookie that binds an OAuth ``state`` to the browser that initiated
#: the connect flow (defends against cross-tenant mailbox binding — audit M1).
_OAUTH_STATE_COOKIE = "silk_sender_oauth_state"


def _set_oauth_state_cookie(response: Response, nonce: str) -> None:
    settings = get_settings()
    response.set_cookie(
        _OAUTH_STATE_COOKIE,
        nonce,
        max_age=settings.oauth_state_ttl_minutes * 60,
        httponly=True,
        # Secure everywhere except local dev (mirrors the fail-closed config).
        secure=settings.environment.strip().lower() != "local",
        # Lax so the cookie rides the top-level GET redirect back from the
        # provider, but is withheld from cross-site sub-resource requests.
        samesite="lax",
        path="/",
    )


_CONNECTABLE = {SenderProviderType.gmail.value, SenderProviderType.microsoft.value}


@router.get("", response_model=list[SenderAccountOut])
def list_accounts(db: DbDep, user: CurrentUser) -> list[SenderAccountOut]:
    factory = resolve_factory(db, user)
    rows = sender_accounts.list_for_factory(db, factory.id)
    return [SenderAccountOut.model_validate(r) for r in rows]


@router.post("/connect/{provider}", response_model=ConnectResponse)
def connect(provider: str, db: DbDep, user: CurrentUser, response: Response) -> ConnectResponse:
    """Begin connecting a new mailbox; returns the provider consent URL."""
    if provider not in _CONNECTABLE:
        raise HTTPException(status_code=400, detail="Unsupported mailbox provider")
    factory = resolve_factory(db, user)
    initiation = sender_oauth.initiate_connect(
        db, factory=factory, provider_type=provider, user=user
    )
    db.commit()
    _set_oauth_state_cookie(response, initiation.state_nonce)
    return ConnectResponse(authorization_url=initiation.authorization_url)


@router.post("/{account_id}/reconnect", response_model=ConnectResponse)
def reconnect(
    db: DbDep,
    user: CurrentUser,
    response: Response,
    account: SenderAccount = Depends(get_owned_sender_account),
) -> ConnectResponse:
    """Re-run the consent flow for an existing (e.g. needs_reauth) mailbox."""
    factory = resolve_factory(db, user)
    initiation = sender_oauth.initiate_connect(
        db,
        factory=factory,
        provider_type=account.provider_type.value,
        user=user,
        account=account,
    )
    db.commit()
    _set_oauth_state_cookie(response, initiation.state_nonce)
    return ConnectResponse(authorization_url=initiation.authorization_url)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(
    db: DbDep,
    user: CurrentUser,
    account: SenderAccount = Depends(get_owned_sender_account),
) -> Response:
    """Disconnect a mailbox: disable it, wipe tokens, and pause its campaigns.

    Pausing is not optional (audit 2026-08-07 C4): campaigns left active on a
    disconnected mailbox had every send blocked at the worker and stranded in
    ``queued`` with no signal to anyone.
    """
    from app.services import notifications, sender_oauth

    account.verification_status = SenderVerificationStatus.disabled
    account.access_token_encrypted = None
    account.refresh_token_encrypted = None
    account.token_expires_at = None
    db.flush()
    paused = sender_oauth.pause_campaigns_for_disconnect(db, account)
    audit.record(
        db,
        action="sender_disconnected",
        entity_type="sender_account",
        entity_id=account.id,
        actor=user,
        factory_id=account.factory_id,
        payload={"email": account.email, "campaigns_paused": paused},
    )
    if paused:
        notifications.notify(
            db,
            factory_id=account.factory_id,
            kind="campaigns_paused_disconnect",
            title="Campaigns paused",
            body=(
                f"{paused} campaign(s) were paused because their sending mailbox "
                f"{account.email} was disconnected. Connect a mailbox and "
                "reactivate them to resume."
            ),
            entity_type="sender_account",
            entity_id=account.id,
        )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/callback/{provider}")
def callback(
    provider: str,
    db: DbDep,
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """OAuth redirect target. No auth — identity travels in the signed ``state``,
    which is bound to the initiating browser via the ``_OAUTH_STATE_COOKIE``."""
    settings = get_settings()
    base = f"{settings.app_base_url.rstrip('/')}{settings.oauth_post_connect_path}"

    def _redirect(query: str) -> RedirectResponse:
        # The single-use state cookie is consumed here regardless of outcome.
        resp = RedirectResponse(url=f"{base}?{query}", status_code=302)
        resp.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
        return resp

    if error:
        log.info("oauth_callback_error", provider=provider, error=error)
        # `error` is attacker-controllable; URL-encode it so it can't inject extra
        # query params into the frontend post-connect URL the SPA parses.
        return _redirect(f"error={quote(error, safe='')}")
    if not code or not state:
        return _redirect("error=missing_code")

    state_cookie = request.cookies.get(_OAUTH_STATE_COOKIE)
    try:
        account = sender_oauth.complete_callback(
            db, provider_type=provider, code=code, state=state, state_cookie=state_cookie
        )
        db.commit()
    except sender_oauth.OAuthStateError:
        db.rollback()
        return _redirect("error=invalid_state")
    except sender_oauth.ConnectError as exc:
        db.rollback()
        log.warning("oauth_connect_failed", provider=provider, error=str(exc))
        return _redirect("error=connect_failed")

    return _redirect(f"connected=1&email={quote(account.email, safe='')}")

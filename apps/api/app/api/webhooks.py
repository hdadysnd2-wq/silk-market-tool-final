"""Inbound engagement webhooks from the sending provider."""

from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.deps import DbDep
from app.config import get_settings
from app.logging import get_logger
from app.schemas.campaign import WebhookEvent
from app.services.sending import record_engagement

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SIGNATURE_HEADER = "X-Smartlead-Signature"


def expected_signature(secret: str, raw_body: bytes) -> str:
    """HMAC-SHA256 hex digest of the raw request body, as the provider signs it."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def _verify_signature(raw_body: bytes, provided: str | None) -> None:
    """Reject the request unless it carries a valid signature.

    Verification is only enforced when a webhook secret is configured. With no
    secret (the local/mock default) the endpoint stays open so the demo's
    synthetic engagement still animates the dashboard.
    """
    settings = get_settings()
    secret = settings.smartlead_webhook_secret
    if not secret:
        # Open ONLY for the local mock demo. If a real sending provider is
        # configured (smartlead_api_key set) or we are not local, refuse: this is
        # an unauthenticated, state-mutating endpoint that can add addresses to the
        # global cross-tenant suppression ledger and auto-pause campaigns.
        # getattr defaults keep the demo/mock path (and lean test doubles) open.
        env = getattr(settings, "environment", "local")
        provider_key = getattr(settings, "smartlead_api_key", "")
        if env != "local" or provider_key:
            log.warning("webhook_secret_missing_but_provider_configured")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Webhook secret not configured",
            )
        return
    if not provided or not hmac.compare_digest(expected_signature(secret, raw_body), provided):
        log.warning("webhook_signature_invalid", has_signature=bool(provided))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature"
        )


@router.post("/smartlead")
async def smartlead_webhook(request: Request, db: DbDep) -> dict:
    """Apply an open/reply/bounce/complaint event to the matching email.

    The mock sending provider posts here itself to animate the dashboard; a real
    Smartlead/Instantly account posts the same shape after webhook setup. When a
    webhook secret is configured, the request must carry a matching HMAC-SHA256
    signature over the raw body in the ``X-Smartlead-Signature`` header.
    """
    raw_body = await request.body()
    _verify_signature(raw_body, request.headers.get(SIGNATURE_HEADER))

    try:
        event = WebhookEvent.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Malformed webhook payload"
        ) from exc

    # The DB write + campaign-health evaluation are blocking; run them in the
    # threadpool so a bounce/engagement burst can't stall the event loop (H1).
    def _apply() -> object:
        email = record_engagement(db, event.message_id, event.event, event.bounce_type)
        db.commit()
        return email

    email = await run_in_threadpool(_apply)
    if email is None:
        return {"detail": "no matching email", "event": event.event}
    return {"detail": "recorded", "event": event.event, "email_status": email.status.value}

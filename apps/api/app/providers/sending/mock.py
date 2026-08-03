"""Deterministic cold-email sending stand-in (Smartlead/Instantly-shaped).

The mock "sends" by writing a line to an on-disk outbox and, when engagement
emulation is on, POSTing synthetic open/reply/bounce webhooks back to the API a
moment later — so the campaign dashboard shows realistic movement in demos
without any real mail leaving the building.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

from app.logging import get_logger
from app.providers.base import (
    MailboxCredentials,
    MailboxIdentity,
    OAuthTokens,
    OutboundEmail,
    ReplyMessage,
    SendResult,
    TokenRefreshError,
)
from app.providers.determinism import rng_for

log = get_logger(__name__)


class MockSendingProvider:
    name = "mock_smartlead"

    def __init__(
        self,
        outbox_dir: str = "./outbox",
        api_base_url: str = "http://localhost:8000",
        emit_engagement: bool = True,
        seed: int = 42,
        webhook_secret: str = "",
    ) -> None:
        self._outbox_dir = Path(outbox_dir)
        self._api_base_url = api_base_url.rstrip("/")
        self._emit_engagement = emit_engagement
        self._seed = seed
        self._webhook_secret = webhook_secret

    def send(self, message: OutboundEmail) -> SendResult:
        message_id = f"mock-{message.message_ref}"
        self._write_outbox(message, message_id)
        if self._emit_engagement:
            self._emit(message, message_id)
        return SendResult(accepted=True, provider_message_id=message_id, provider_name=self.name)

    def register_webhook_events(self) -> None:  # nothing to register for the mock
        return None

    # -- internals ---------------------------------------------------------

    def _write_outbox(self, message: OutboundEmail, message_id: str) -> None:
        try:
            self._outbox_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "message_id": message_id,
                "to": message.to_email,
                "from": message.from_email,
                "subject": message.subject,
                "sending_domain": message.sending_domain,
                "unsubscribe_url": message.unsubscribe_url,
                "sent_at": datetime.now(UTC).isoformat(),
            }
            path = self._outbox_dir / f"{message_id}.json"
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - outbox is best effort
            log.warning("outbox_write_failed", error=str(exc))

    def _emit(self, message: OutboundEmail, message_id: str) -> None:
        """Fire synthetic engagement events at the webhook endpoint."""
        rng = rng_for(message.message_ref, self._seed)
        events: list[dict] = [{"event": "sent", "message_id": message_id}]

        roll = rng.random()
        if roll < 0.04:
            events.append({"event": "bounced", "message_id": message_id, "bounce_type": "hard"})
        else:
            if rng.random() < 0.55:
                events.append({"event": "opened", "message_id": message_id})
                if rng.random() < 0.18:
                    events.append({"event": "replied", "message_id": message_id})
            if rng.random() < 0.002:
                events.append({"event": "complained", "message_id": message_id})

        url = f"{self._api_base_url}/api/v1/webhooks/smartlead"
        for event in events:
            try:
                raw = json.dumps(event).encode("utf-8")
                headers = {"Content-Type": "application/json"}
                if self._webhook_secret:
                    import hashlib
                    import hmac

                    headers["X-Smartlead-Signature"] = hmac.new(
                        self._webhook_secret.encode("utf-8"), raw, hashlib.sha256
                    ).hexdigest()
                httpx.post(url, content=raw, headers=headers, timeout=5.0)
            except httpx.HTTPError as exc:
                # In tests / offline demos the API may not be reachable over HTTP;
                # the send itself still succeeded.
                log.info("mock_webhook_unreachable", error=str(exc), event=event["event"])
                return


# Mock scopes mirror the narrow real ones (send + read for reply detection).
MOCK_SCOPES = "mailbox.send mailbox.read"


def _encode_email(email: str) -> str:
    return base64.urlsafe_b64encode(email.encode("utf-8")).decode("ascii")


def _decode_email(token: str) -> str:
    try:
        return base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return "mock-mailbox@example.com"


class MockMailboxProvider:
    """Deterministic, fully in-process stand-in for a connected OAuth mailbox.

    Simulates the entire authorization-code flow without any external call, so
    the connect → verify → send → poll path runs end to end in demos, CI and the
    Playwright e2e (the "mocked OAuth" flow) with no Google/Microsoft app.

    The mailbox address is carried through the handshake: it is embedded (base64)
    in the synthetic auth ``code`` and echoed back in the token so ``verify_mailbox``
    can recover it — the same shape a real provider's profile lookup would yield.
    """

    def __init__(self, provider_type: str = "mock", outbox_dir: str = "./outbox") -> None:
        # Preserve the requested provider so the UI can show "gmail (mock)".
        self.provider_type = provider_type
        self.name = f"mock_{provider_type}_mailbox"
        self.scopes = MOCK_SCOPES
        self._outbox_dir = Path(outbox_dir)

    def authorization_url(
        self, *, state: str, redirect_uri: str, login_hint: str | None = None
    ) -> str:
        # Point straight back at our own callback with a synthetic code, so the
        # browser round-trips without a real consent screen.
        email = login_hint or f"{self.provider_type}-outreach@mailbox.example"
        code = f"mock.{_encode_email(email)}"
        joiner = "&" if "?" in redirect_uri else "?"
        return f"{redirect_uri}{joiner}code={quote(code)}&state={quote(state)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokens:
        email = _decode_email(code.split(".", 1)[1]) if "." in code else "mock@example.com"
        return OAuthTokens(
            access_token=f"mock-access.{_encode_email(email)}",
            refresh_token=f"mock-refresh.{_encode_email(email)}",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=MOCK_SCOPES,
        )

    def refresh(self, *, refresh_token: str) -> OAuthTokens:
        # A revoked/expired grant is simulated by the sentinel token below, so
        # tests can exercise the reauth path deterministically.
        if "revoked" in refresh_token or refresh_token == "":
            raise TokenRefreshError("mock refresh token revoked")
        email = (
            _decode_email(refresh_token.split(".", 1)[1])
            if "." in refresh_token
            else "mock@example.com"
        )
        return OAuthTokens(
            access_token=f"mock-access.{_encode_email(email)}",
            refresh_token=refresh_token,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=MOCK_SCOPES,
        )

    def verify_mailbox(self, creds: MailboxCredentials) -> MailboxIdentity:
        email = creds.email or (
            _decode_email(creds.access_token.split(".", 1)[1])
            if "." in creds.access_token
            else "mock@example.com"
        )
        account_id = "mock-" + hashlib.sha1(email.encode("utf-8")).hexdigest()[:12]  # noqa: S324
        return MailboxIdentity(
            email=email,
            provider_account_id=account_id,
            display_name=email.split("@", 1)[0].replace(".", " ").title(),
        )

    def send(self, creds: MailboxCredentials, message: OutboundEmail) -> SendResult:
        message_id = f"mock-mailbox-{message.message_ref}"
        try:
            self._outbox_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "message_id": message_id,
                "mailbox": creds.email,
                "to": message.to_email,
                "subject": message.subject,
                "sent_at": datetime.now(UTC).isoformat(),
            }
            (self._outbox_dir / f"{message_id}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover - outbox is best effort
            log.warning("mailbox_outbox_write_failed", error=str(exc))
        return SendResult(accepted=True, provider_message_id=message_id, provider_name=self.name)

    def fetch_replies(self, creds: MailboxCredentials, since: datetime) -> list[ReplyMessage]:
        # The deterministic mock reports no replies; reply handling is exercised
        # via ``services.replies`` with an injected provider in tests.
        return []

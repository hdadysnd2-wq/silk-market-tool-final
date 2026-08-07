"""Fail-closed gate for a configured-but-unproven cold-send slot.

Every other provider slot follows the registry's one rule — key present → real
adapter — because the worst case of a wrong guess is a degraded *read* (a
missing enrichment field, an empty lead list). The cold-send slot is different:
its worst case is an outbound email that reaches a real person **without the
one-click List-Unsubscribe headers RFC 8058 (and I4) require**, which is both a
compliance breach and unrecoverable — you cannot un-send it.

Those headers are not emitted by our adapter. Smartlead emits them from the
campaign *sequence template*, populated from the custom fields the adapter
attaches to the lead. Whether that template is wired correctly is a console
setting that no offline test can observe. So the key alone is not sufficient
evidence to send: the operator must also assert the template is configured
(``SMARTLEAD_SEQUENCE_VERIFIED=1``) after checking it against a real account.

Until then the registry hands out this gate. It satisfies ``SendingProvider``
and refuses every send with an actionable reason. ``send_email`` turns a
non-accepted result into ``SendBlocked``, so the queued email stays queued and
auditable rather than being silently dropped or half-sent.
"""

from __future__ import annotations

from app.logging import get_logger
from app.providers.base import OutboundEmail, SendResult

log = get_logger(__name__)

#: Reason surfaced on every refused send. Names the exact env var to set so the
#: operator is never left guessing why a configured provider will not send.
GATE_REASON = (
    "Smartlead cold-send is gated: SMARTLEAD_API_KEY is set but the campaign "
    "sequence template that emits the one-click List-Unsubscribe headers is "
    "unverified. Configure it, then set SMARTLEAD_SEQUENCE_VERIFIED=1 "
    "(see docs/PHASE3_ADAPTER_READINESS.md)."
)

#: Refusal reason when no real sending provider is configured outside local.
#: An email the mock "sends" reaches nobody while the row is marked sent —
#: a compliance-grade lie in production. Name every way out.
NO_PROVIDER_REASON = (
    "No real sending provider is configured and ENVIRONMENT is not 'local'. "
    "Either set SMARTLEAD_API_KEY (and verify the sequence, "
    "SMARTLEAD_SEQUENCE_VERIFIED=1), connect a mailbox via Google/Microsoft "
    "OAuth credentials, or — for a keyless demo only — explicitly set "
    "ALLOW_MOCK_SENDING=1."
)


class GatedSendingProvider:
    """Stands in for a live sending adapter that is not yet cleared to send."""

    def __init__(self, gated_name: str, reason: str = GATE_REASON) -> None:
        #: Reported to /health and stored nowhere — a gated slot never records a
        #: send — so the summary reads e.g. "smartlead (gated)".
        self.name = f"{gated_name} (gated)"
        self._reason = reason

    def send(self, message: OutboundEmail) -> SendResult:
        log.error("send_blocked_provider_gated", to=message.to_email, reason=self._reason)
        return SendResult(
            accepted=False,
            provider_message_id=None,
            provider_name=self.name,
            error=self._reason,
        )

    def register_webhook_events(self) -> None:
        return None


class GatedMailboxProvider:
    """Fail-closed stand-in for the mailbox slot when no OAuth app is configured.

    Satisfies ``MailboxProvider`` without ever pretending to work: sends are
    refused with an actionable reason (``send_email`` keeps the row ``queued``),
    OAuth-flow entry points raise so the connect UI surfaces the misconfiguration
    loudly, and reply polling reports nothing rather than fabricating traffic.
    """

    scopes = ""

    def __init__(self, provider_type: str, reason: str = NO_PROVIDER_REASON) -> None:
        self.name = f"{provider_type} (gated)"
        self.provider_type = provider_type
        self._reason = reason

    def authorization_url(self, *, state, redirect_uri, login_hint=None) -> str:
        raise RuntimeError(self._reason)

    def exchange_code(self, *, code, redirect_uri):
        raise RuntimeError(self._reason)

    def refresh(self, *, refresh_token):
        raise RuntimeError(self._reason)

    def verify_mailbox(self, creds):
        raise RuntimeError(self._reason)

    def send(self, creds, message: OutboundEmail) -> SendResult:
        log.error("send_blocked_provider_gated", to=message.to_email, reason=self._reason)
        return SendResult(
            accepted=False,
            provider_message_id=None,
            provider_name=self.name,
            error=self._reason,
        )

    def fetch_replies(self, creds, since) -> list:
        return []

"""Smartlead cold-email sending adapter (campaign-based).

Design invariants this adapter encodes:

* **I6 — cold email only via Smartlead/Instantly, never a transactional ESP.**
  Cold outreach leaves the platform through Smartlead (or Instantly) or a
  factory's own connected mailbox — never SendGrid/SES/Mailgun/Postmark/etc.
  This module imports only ``httpx`` (an AST test bans transactional-ESP SDKs
  under ``providers/sending/``).

* **Campaign-based rework.** Smartlead does NOT expose a flat "send one email"
  call. Its model is: you create a campaign with a sequence, then *add leads*
  to that campaign; Smartlead then sends each lead the sequence on the campaign's
  schedule. The previous adapter POSTed a flat one-shot payload to
  ``/api/v1/email/reply`` — the *reply-to-an-existing-email* endpoint — which is
  the wrong shape and the wrong endpoint for cold outreach. This rework targets
  the **add-lead-to-campaign** endpoint instead:

      POST {SMARTLEAD_BASE}/campaigns/{campaign_id}/leads?api_key=...

  ``message.campaign_ref`` MUST carry the Smartlead campaign id (the sending
  service already sets ``campaign_ref = str(campaign.id)``; for a live Smartlead
  slot that value must be the *Smartlead* campaign id, mapped from our campaign).

* **I4 — one-click List-Unsubscribe intent is preserved.** RFC-8058 requires the
  outbound message to carry ``List-Unsubscribe: <url>`` and
  ``List-Unsubscribe-Post: List-Unsubscribe=One-Click``. Those are message
  *headers*, but Smartlead emits headers from the campaign's sequence template,
  not from the add-leads call. So the unsubscribe URL and the exact header values
  are carried here as lead ``custom_fields`` (personalization variables), and the
  campaign sequence template MUST be configured to emit those two headers from
  those variables. See the "UNPROVEN" note below.

* **UNPROVEN pending live-smoke (PR #40).** No live send has validated this path.
  The endpoint + payload SHAPE match Smartlead's public docs (``lead_list`` of
  ``{email, first_name, last_name, custom_fields}`` + a ``settings`` object), but
  the exact custom-field NAMES the campaign sequence references, and the wiring
  that makes the sequence emit the one-click List-Unsubscribe headers, are a
  console configuration step that can only be confirmed against a real Smartlead
  account with SPF/DKIM/DMARC in place. Do not treat the custom-field wiring as
  proven. This adapter never sends on its own — Smartlead does, per the campaign
  schedule, after the lead is added.
"""

from __future__ import annotations

import httpx

from app.logging import get_logger
from app.providers.base import OutboundEmail, SendResult
from app.providers.http_errors import safe_error

log = get_logger(__name__)

#: Smartlead REST base. The add-leads endpoint is
#: ``{SMARTLEAD_BASE}/campaigns/{campaign_id}/leads`` (NOT the reply endpoint).
SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"


def _split_name(full_name: str | None) -> tuple[str, str]:
    """Best-effort first/last split for Smartlead's lead fields.

    Smartlead stores ``first_name``/``last_name`` separately; we only carry a
    single ``to_name``. First whitespace token → first name, remainder → last
    name. Missing/blank name degrades to empty strings (never fabricated).
    """
    if not full_name or not full_name.strip():
        return "", ""
    parts = full_name.split()
    return parts[0], " ".join(parts[1:])


class SmartleadSendingProvider:
    name = "smartlead"

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def send(self, message: OutboundEmail) -> SendResult:
        """Add the recipient as a lead on the Smartlead campaign.

        ``message.campaign_ref`` is used as the Smartlead ``{campaign_id}``. The
        composed subject/body and the one-click unsubscribe intent travel as the
        lead's ``custom_fields`` so the campaign sequence template can reference
        them as personalization variables (and emit the List-Unsubscribe headers).

        Any non-2xx, HTTP error, non-JSON body, or unexpected response shape
        degrades to ``accepted=False`` — it never raises — so one bad Smartlead
        response can't crash the approval/send flow.
        """
        campaign_id = message.campaign_ref
        first_name, last_name = _split_name(message.to_name)
        body_html = message.body_html or message.body_text.replace("\n", "<br>")

        # Carry the composed message + one-click List-Unsubscribe (RFC 8058)
        # intent as personalization variables. NOTE (UNPROVEN): the campaign
        # sequence template must reference these exact custom-field names and
        # emit `List-Unsubscribe: <url>` + `List-Unsubscribe-Post:
        # List-Unsubscribe=One-Click` from them — a console step confirmed only
        # by the live-smoke (PR #40).
        custom_fields = {
            "subject": message.subject,
            "email_body_html": body_html,
            "email_body_text": message.body_text,
            "unsubscribe_url": message.unsubscribe_url,
            "list_unsubscribe": f"<{message.unsubscribe_url}>",
            "list_unsubscribe_post": "List-Unsubscribe=One-Click",
            "message_ref": message.message_ref,
        }
        payload = {
            "lead_list": [
                {
                    "email": message.to_email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "custom_fields": custom_fields,
                }
            ],
            # Respect Smartlead's workspace-level suppression: do NOT bypass the
            # global block list or the unsubscribe list (I4 / compliance). We only
            # skip re-adding a lead already present in another campaign.
            "settings": {
                "ignore_global_block_list": False,
                "ignore_unsubscribe_list": False,
                "ignore_duplicate_leads_in_other_campaign": True,
            },
        }

        url = f"{SMARTLEAD_BASE}/campaigns/{campaign_id}/leads"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, params={"api_key": self._api_key}, json=payload)
                response.raise_for_status()
                body = response.json()
            if not isinstance(body, dict):
                raise ValueError(f"unexpected Smartlead response shape: {type(body).__name__}")
            message_id = _lead_ref(body, campaign_id, message.to_email)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            # The key rides in the query string, so httpx error text embeds it.
            # Use a status/type-only rendering for BOTH the log and the persisted
            # SendResult.error, or the live key leaks into logs and Email state.
            err = safe_error(exc)
            log.error("smartlead_send_failed", to=message.to_email, error=err)
            return SendResult(
                accepted=False, provider_message_id=None, provider_name=self.name, error=err
            )
        return SendResult(accepted=True, provider_message_id=message_id, provider_name=self.name)

    def register_webhook_events(self) -> None:
        # Webhook registration is a one-time console/API setup step per account;
        # left as a no-op for the MVP.
        return None


def _lead_ref(body: dict, campaign_id: str, email: str) -> str:
    """Best-effort lead identifier from Smartlead's add-leads response.

    Smartlead's add-leads response shape varies by API version — reported keys
    include ``lead_ids``/``upload_count``/``added_count``/``already_added_to_campaign``
    (UNPROVEN until live-smoke). We prefer a returned lead id and otherwise fall
    back to a ``{campaign_id}:{email}`` reference so a success always carries a
    stable id. This never raises: a 2xx add is treated as accepted.
    """
    lead_ids = body.get("lead_ids")
    if isinstance(lead_ids, list) and lead_ids:
        return str(lead_ids[0])
    lead_id = body.get("lead_id") or body.get("id")
    if lead_id is not None:
        return str(lead_id)
    return f"{campaign_id}:{email}"

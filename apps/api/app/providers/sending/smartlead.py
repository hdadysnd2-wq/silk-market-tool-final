"""Smartlead cold-email sending adapter.

Cold email is sent through Smartlead (or Instantly), never a transactional ESP
such as SendGrid or SES, per the deliverability rules.
"""

from __future__ import annotations

import httpx

from app.logging import get_logger
from app.providers.base import OutboundEmail, SendResult

log = get_logger(__name__)

SMARTLEAD_URL = "https://server.smartlead.ai/api/v1/email/reply"


class SmartleadSendingProvider:
    name = "smartlead"

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def send(self, message: OutboundEmail) -> SendResult:
        payload = {
            "to_email": message.to_email,
            "to_name": message.to_name,
            "subject": message.subject,
            "body_html": message.body_html or message.body_text.replace("\n", "<br>"),
            "from_name": message.from_name,
            "from_email": message.from_email,
            "reply_to": message.reply_to,
            "custom_headers": {
                "List-Unsubscribe": f"<{message.unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    SMARTLEAD_URL, params={"api_key": self._api_key}, json=payload
                )
                response.raise_for_status()
                message_id = response.json().get("message_id")
        except httpx.HTTPError as exc:
            log.error("smartlead_send_failed", to=message.to_email, error=str(exc))
            return SendResult(
                accepted=False, provider_message_id=None, provider_name=self.name, error=str(exc)
            )
        return SendResult(accepted=True, provider_message_id=message_id, provider_name=self.name)

    def register_webhook_events(self) -> None:
        # Webhook registration is a one-time console/API setup step per account;
        # left as a no-op for the MVP.
        return None

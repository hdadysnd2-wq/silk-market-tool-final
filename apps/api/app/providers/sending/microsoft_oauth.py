"""Microsoft mailbox adapter — sends on behalf of a connected Microsoft 365 account.

Uses the OAuth2 authorization-code flow and Microsoft Graph. Scopes are kept
narrow: ``Mail.Send`` to send, ``Mail.Read`` for reply detection, plus
``offline_access`` (refresh token) and ``openid email`` (mailbox address).
"""

from __future__ import annotations

import contextlib
import re
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx

from app.logging import get_logger
from app.providers.base import (
    MailboxCredentials,
    MailboxIdentity,
    MailboxVerificationError,
    OAuthTokens,
    OutboundEmail,
    ReplyMessage,
    SendResult,
)
from app.providers.sending._oauth_http import exchange

log = get_logger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Narrowest scopes for send + reply detection.
GRAPH_SCOPES = "offline_access openid email Mail.Send Mail.Read"


class MicrosoftGraphProvider:
    provider_type = "microsoft"
    name = "microsoft_graph"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant: str = "common",
        timeout: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._tenant = tenant or "common"
        self._timeout = timeout
        self.scopes = GRAPH_SCOPES

    @property
    def _auth_url(self) -> str:
        return f"https://login.microsoftonline.com/{self._tenant}/oauth2/v2.0/authorize"

    @property
    def _token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self._tenant}/oauth2/v2.0/token"

    # -- OAuth ------------------------------------------------------------

    def authorization_url(
        self, *, state: str, redirect_uri: str, login_hint: str | None = None
    ) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.scopes,
            "state": state,
            "response_mode": "query",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{self._auth_url}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokens:
        return exchange(
            token_url=self._token_url,
            client_id=self._client_id,
            client_secret=self._client_secret,
            data={
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": self.scopes,
            },
            timeout=self._timeout,
        )

    def refresh(self, *, refresh_token: str) -> OAuthTokens:
        return exchange(
            token_url=self._token_url,
            client_id=self._client_id,
            client_secret=self._client_secret,
            data={
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": self.scopes,
            },
            timeout=self._timeout,
        )

    # -- Mailbox ----------------------------------------------------------

    def verify_mailbox(self, creds: MailboxCredentials) -> MailboxIdentity:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{GRAPH_BASE}/me", headers=self._auth(creds))
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise MailboxVerificationError(f"graph profile lookup failed: {exc}") from exc
        email = data.get("mail") or data.get("userPrincipalName")
        if not email:
            raise MailboxVerificationError("graph profile returned no address")
        return MailboxIdentity(
            email=email, provider_account_id=data.get("id"), display_name=data.get("displayName")
        )

    @staticmethod
    def _build_send_body(message: OutboundEmail) -> dict:
        body = {
            "message": {
                "subject": message.subject,
                "body": {
                    "contentType": "HTML" if message.body_html else "Text",
                    "content": message.body_html or message.body_text,
                },
                "toRecipients": [{"emailAddress": {"address": message.to_email}}],
                "internetMessageHeaders": [
                    {"name": "List-Unsubscribe", "value": f"<{message.unsubscribe_url}>"},
                    # RFC 8058 one-click (audit H8): without this header,
                    # Gmail/Yahoo will not fire the POST-only /u unsubscribe
                    # for mail sent via Microsoft mailboxes.
                    {"name": "List-Unsubscribe-Post", "value": "List-Unsubscribe=One-Click"},
                ],
            },
            "saveToSentItems": True,
        }
        if message.reply_to:
            body["message"]["replyTo"] = [{"emailAddress": {"address": message.reply_to}}]
        return body

    def send(self, creds: MailboxCredentials, message: OutboundEmail) -> SendResult:
        body = self._build_send_body(message)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{GRAPH_BASE}/me/sendMail", headers=self._auth(creds), json=body
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("graph_send_failed", to=message.to_email, error=str(exc))
            return SendResult(
                accepted=False, provider_message_id=None, provider_name=self.name, error=str(exc)
            )
        # sendMail returns 202 with no id; use our message ref for correlation.
        return SendResult(
            accepted=True, provider_message_id=message.message_ref, provider_name=self.name
        )

    def fetch_replies(self, creds: MailboxCredentials, since: datetime) -> list[ReplyMessage]:
        iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        replies: list[ReplyMessage] = []
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(
                    f"{GRAPH_BASE}/me/messages",
                    headers=self._auth(creds),
                    params={
                        "$filter": f"receivedDateTime ge {iso}",
                        # bodyPreview carries the failed address on Exchange NDRs.
                        "$select": (
                            "from,toRecipients,subject,receivedDateTime,"
                            "internetMessageId,bodyPreview"
                        ),
                        "$top": 50,
                    },
                )
                resp.raise_for_status()
                for msg in resp.json().get("value", []):
                    reply = self._parse_reply(msg)
                    if reply:
                        replies.append(reply)
        except httpx.HTTPError as exc:
            log.warning("graph_fetch_replies_failed", error=str(exc))
        return replies

    # -- internals --------------------------------------------------------

    @staticmethod
    def _auth(creds: MailboxCredentials) -> dict[str, str]:
        return {"Authorization": f"Bearer {creds.access_token}"}

    @staticmethod
    def _parse_reply(msg: dict) -> ReplyMessage | None:
        sender = (msg.get("from") or {}).get("emailAddress", {}).get("address")
        if not sender:
            return None
        received = datetime.now(UTC)
        if msg.get("receivedDateTime"):
            with contextlib.suppress(ValueError):
                received = datetime.fromisoformat(msg["receivedDateTime"].replace("Z", "+00:00"))
        recipients = msg.get("toRecipients") or []
        to_email = recipients[0].get("emailAddress", {}).get("address") if recipients else None
        return ReplyMessage(
            from_email=sender.lower(),
            to_email=to_email,
            subject=msg.get("subject"),
            received_at=received,
            provider_message_id=msg.get("internetMessageId", msg.get("id", "")),
            in_reply_to=None,
            failed_recipient=_ndr_failed_recipient(sender, msg.get("bodyPreview")),
        )


_ADDR_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_NDR_LOCALPARTS = ("postmaster", "mailer-daemon", "microsoftexchange")


def _ndr_failed_recipient(sender: str, body_preview: str | None) -> str | None:
    """Extract the failed recipient from an Exchange non-delivery report.

    Graph exposes no NDR message-class in a metadata list query, so we detect the
    report by its machine sender and read the failed address out of ``bodyPreview``
    ("Your message to <addr> couldn't be delivered."). Returns ``None`` for
    ordinary mail — the reply/bounce split then treats it as a human reply.
    """
    local = sender.split("@", 1)[0].strip().lower()
    if not any(local.startswith(p) for p in _NDR_LOCALPARTS):
        return None
    if not body_preview:
        return None
    for match in _ADDR_RE.finditer(body_preview):
        addr = match.group(0).lower()
        # Skip the NDR sender's own address if it appears in the preview text.
        if addr != sender.lower():
            return addr
    return None

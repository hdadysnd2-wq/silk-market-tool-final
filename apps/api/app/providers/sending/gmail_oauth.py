"""Gmail mailbox adapter — sends on behalf of a factory's connected Google account.

Uses the OAuth2 authorization-code flow and the Gmail API. Scopes are kept as
narrow as the task allows: ``gmail.send`` to send and ``gmail.readonly`` to detect
replies for reply-based sequence stopping — nothing that would let the platform
read or modify unrelated mail beyond what reply detection requires.
"""

from __future__ import annotations

import base64
import contextlib
from datetime import UTC, datetime
from email.mime.text import MIMEText
from email.utils import parseaddr, parsedate_to_datetime
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

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Narrowest scopes: send + read (reply detection). openid/email give the address.
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send "
    "https://www.googleapis.com/auth/gmail.readonly openid email"
)


class GmailOAuthProvider:
    provider_type = "gmail"
    name = "gmail_oauth"

    def __init__(self, client_id: str, client_secret: str, timeout: float = 30.0) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout
        self.scopes = GMAIL_SCOPES

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
            # offline + consent are what actually yield a refresh token.
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokens:
        return exchange(
            token_url=TOKEN_URL,
            client_id=self._client_id,
            client_secret=self._client_secret,
            data={
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=self._timeout,
        )

    def refresh(self, *, refresh_token: str) -> OAuthTokens:
        tokens = exchange(
            token_url=TOKEN_URL,
            client_id=self._client_id,
            client_secret=self._client_secret,
            data={"refresh_token": refresh_token, "grant_type": "refresh_token"},
            timeout=self._timeout,
        )
        # Google does not resend the refresh token; keep the existing one.
        if tokens.refresh_token is None:
            tokens = OAuthTokens(
                access_token=tokens.access_token,
                refresh_token=refresh_token,
                expires_at=tokens.expires_at,
                scopes=tokens.scopes,
            )
        return tokens

    # -- Mailbox ----------------------------------------------------------

    def verify_mailbox(self, creds: MailboxCredentials) -> MailboxIdentity:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{API_BASE}/profile", headers=self._auth(creds))
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise MailboxVerificationError(f"gmail profile lookup failed: {exc}") from exc
        email = data.get("emailAddress")
        if not email:
            raise MailboxVerificationError("gmail profile returned no address")
        return MailboxIdentity(email=email, provider_account_id=email, display_name=None)

    def send(self, creds: MailboxCredentials, message: OutboundEmail) -> SendResult:
        raw = self._build_raw(creds.email, message)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{API_BASE}/messages/send",
                    headers=self._auth(creds),
                    json={"raw": raw},
                )
                resp.raise_for_status()
                message_id = resp.json().get("id")
        except httpx.HTTPError as exc:
            log.error("gmail_send_failed", to=message.to_email, error=str(exc))
            return SendResult(
                accepted=False, provider_message_id=None, provider_name=self.name, error=str(exc)
            )
        return SendResult(accepted=True, provider_message_id=message_id, provider_name=self.name)

    def fetch_replies(self, creds: MailboxCredentials, since: datetime) -> list[ReplyMessage]:
        after = int(since.timestamp())
        replies: list[ReplyMessage] = []
        try:
            with httpx.Client(timeout=self._timeout) as client:
                listing = client.get(
                    f"{API_BASE}/messages",
                    headers=self._auth(creds),
                    params={"q": f"in:inbox after:{after}", "maxResults": 50},
                )
                listing.raise_for_status()
                for stub in listing.json().get("messages", []):
                    detail = client.get(
                        f"{API_BASE}/messages/{stub['id']}",
                        headers=self._auth(creds),
                        params={
                            "format": "metadata",
                            "metadataHeaders": [
                                "From",
                                "To",
                                "Subject",
                                "In-Reply-To",
                                "Date",
                                # Gmail stamps the failed address here on bounce NDRs.
                                "X-Failed-Recipients",
                            ],
                        },
                    )
                    if detail.status_code >= 400:
                        continue
                    reply = self._parse_reply(detail.json())
                    if reply:
                        replies.append(reply)
        except httpx.HTTPError as exc:
            log.warning("gmail_fetch_replies_failed", error=str(exc))
        return replies

    # -- internals --------------------------------------------------------

    @staticmethod
    def _auth(creds: MailboxCredentials) -> dict[str, str]:
        return {"Authorization": f"Bearer {creds.access_token}"}

    @staticmethod
    def _build_raw(from_email: str, message: OutboundEmail) -> str:
        mime = MIMEText(
            message.body_html or message.body_text,
            "html" if message.body_html else "plain",
            "utf-8",
        )
        mime["To"] = message.to_email
        mime["From"] = f"{message.from_name} <{from_email}>"
        mime["Subject"] = message.subject
        if message.reply_to:
            mime["Reply-To"] = message.reply_to
        mime["List-Unsubscribe"] = f"<{message.unsubscribe_url}>"
        mime["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        return base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")

    @staticmethod
    def _parse_reply(payload: dict) -> ReplyMessage | None:
        headers = {
            h["name"].lower(): h["value"] for h in payload.get("payload", {}).get("headers", [])
        }
        from_hdr = headers.get("from")
        if not from_hdr:
            return None
        received = datetime.now(UTC)
        if headers.get("date"):
            with contextlib.suppress(TypeError, ValueError):
                received = parsedate_to_datetime(headers["date"])
        failed = headers.get("x-failed-recipients")
        failed_recipient = parseaddr(failed)[1].lower() or None if failed else None
        return ReplyMessage(
            from_email=parseaddr(from_hdr)[1].lower(),
            to_email=parseaddr(headers.get("to", ""))[1] or None,
            subject=headers.get("subject"),
            received_at=received,
            provider_message_id=payload.get("id", ""),
            in_reply_to=headers.get("in-reply-to"),
            failed_recipient=failed_recipient,
        )

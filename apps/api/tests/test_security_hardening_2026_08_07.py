"""Phase-2 security-hardening locks (audit 2026-08-07 §6/§7).

- Gmail MIME header injection: CR/LF stripped from user-controlled headers.
- Microsoft RFC 8058: List-Unsubscribe-Post present for one-click.
- /auth/register is rate-throttled like the other auth routes.
- /docs and /metrics are gated outside local.
"""

from __future__ import annotations

from app.providers.base import OutboundEmail


def _msg(**over) -> OutboundEmail:
    base = {
        "to_email": "buyer@acme.example",
        "to_name": "Buyer",
        "subject": "Hello",
        "body_text": "hi",
        "body_html": "<p>hi</p>",
        "from_name": "Factory",
        "from_email": "me@factory.example",
        "reply_to": None,
        "sending_domain": "factory.example",
        "unsubscribe_url": "https://api.example/u/tok",
        "campaign_ref": "c-1",
        "message_ref": "m-1",
    }
    base.update(over)
    return OutboundEmail(**base)


def test_gmail_strips_crlf_from_headers():
    from app.providers.sending.gmail_oauth import GmailOAuthProvider

    injected = "Legit\r\nBcc: victim@evil.example"
    raw = GmailOAuthProvider._build_raw("me@factory.example", _msg(subject=injected))
    import base64

    decoded = base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
    # The CRLF is collapsed to spaces, so "Bcc:" survives only as inline subject
    # text on the Subject line — never as a header line of its own.
    assert "\nBcc:" not in decoded
    assert "\r\nBcc:" not in decoded
    for line in decoded.splitlines():
        assert not line.startswith("Bcc:")


def test_gmail_strips_crlf_from_from_name():
    from app.providers.sending.gmail_oauth import GmailOAuthProvider

    raw = GmailOAuthProvider._build_raw(
        "me@factory.example", _msg(from_name="Acme\r\nX-Injected: 1")
    )
    import base64

    decoded = base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
    # Collapsed to a space inside the From display name — never its own header.
    for line in decoded.splitlines():
        assert not line.startswith("X-Injected")


def test_microsoft_sets_one_click_unsubscribe_post():
    from app.providers.sending.microsoft_oauth import MicrosoftGraphProvider

    body = MicrosoftGraphProvider._build_send_body(_msg())
    headers = body["message"]["internetMessageHeaders"]
    names = {h["name"] for h in headers}
    assert "List-Unsubscribe" in names
    assert "List-Unsubscribe-Post" in names


def test_register_is_throttled(client, monkeypatch):
    from app.services import rate_limit

    calls = []
    real = rate_limit.check

    def _spy(key, **kw):
        calls.append(key)
        return real(key, **kw)

    monkeypatch.setattr(rate_limit, "check", _spy)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@factory.example",
            "password": "Passw0rd!234",
            "full_name": "New Owner",
            "factory_name_ar": "مصنع",
            "factory_name_en": "Factory",
            "locale": "en",
        },
    )
    assert any(k.startswith("register:ip:") for k in calls)


def test_docs_and_metrics_gated_outside_local(monkeypatch):
    """Production app exposes no /docs, no openapi, and 404s /metrics sans token."""
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "t" * 44)
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("REQUIRE_OBJECT_STORAGE", "0")
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    monkeypatch.setenv("API_BASE_URL", "https://api.silk.example")
    monkeypatch.setenv("APP_BASE_URL", "https://app.silk.example")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert client.get("/docs").status_code == 404
        assert client.get("/api/v1/openapi.json").status_code == 404
        assert client.get("/metrics").status_code == 404
    finally:
        get_settings.cache_clear()

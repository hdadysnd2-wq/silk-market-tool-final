"""Smartlead adapter posts to the campaign-leads API with the campaign payload.

Offline: ``httpx.Client.post`` is monkeypatched to capture the request and
return a canned Smartlead-shaped response — NO network. Locks the rework:

* the adapter POSTs to ``campaigns/{campaign_ref}/leads`` (the add-lead endpoint),
  NOT the old ``/email/reply`` endpoint;
* the JSON body carries the recipient in ``lead_list`` and the subject/body/
  unsubscribe intent in ``custom_fields`` (RFC-8058 one-click List-Unsubscribe, I4);
* a 2xx add → ``SendResult(accepted=True, ...)`` with a lead id;
* a failure (post raises / non-2xx) → ``SendResult(accepted=False, error=...)``
  without raising (degrade, never crash the approval/send flow).
"""

from __future__ import annotations

import httpx
import pytest

from app.providers.base import OutboundEmail
from app.providers.sending.smartlead import SMARTLEAD_BASE, SmartleadSendingProvider


def _message() -> OutboundEmail:
    return OutboundEmail(
        to_email="buyer@acme.example",
        to_name="Ada Lovelace",
        subject="Saudi dates for your shelves",
        body_text="Hello Ada,\nWe export premium dates.",
        body_html="<p>Hello Ada,</p>",
        from_name="Silk Outreach",
        from_email="outreach@silk.example",
        reply_to="sales@silk.example",
        sending_domain="silk.example",
        unsubscribe_url="https://silk.example/u/tok123",
        campaign_ref="camp-123",
        message_ref="msg-9",
    )


class _Resp:
    def __init__(self, json_value=None, raise_status=False):
        self._json_value = json_value
        self._raise_status = raise_status

    def raise_for_status(self):
        if self._raise_status:
            raise httpx.HTTPStatusError("500 Server Error", request=None, response=None)
        return None

    def json(self):
        return self._json_value


def test_posts_to_campaign_leads_endpoint_with_campaign_payload(monkeypatch):
    captured: dict = {}

    def fake_post(self, url, *, params=None, json=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        captured["json"] = json
        return _Resp(json_value={"lead_ids": [4242], "upload_count": 1})

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = SmartleadSendingProvider("secret-key").send(_message())

    # (a) add-lead-to-campaign endpoint for campaign camp-123 — NOT /email/reply.
    assert captured["url"] == f"{SMARTLEAD_BASE}/campaigns/camp-123/leads"
    assert "email/reply" not in captured["url"]
    assert captured["params"] == {"api_key": "secret-key"}

    # (b) recipient in lead_list; subject/body/unsubscribe carried in custom_fields.
    body = captured["json"]
    lead = body["lead_list"][0]
    assert lead["email"] == "buyer@acme.example"
    assert lead["first_name"] == "Ada"
    assert lead["last_name"] == "Lovelace"
    cf = lead["custom_fields"]
    assert cf["subject"] == "Saudi dates for your shelves"
    assert cf["email_body_html"] == "<p>Hello Ada,</p>"
    assert "We export premium dates." in cf["email_body_text"]
    assert cf["unsubscribe_url"] == "https://silk.example/u/tok123"
    # RFC-8058 one-click List-Unsubscribe intent preserved (I4).
    assert cf["list_unsubscribe"] == "<https://silk.example/u/tok123>"
    assert cf["list_unsubscribe_post"] == "List-Unsubscribe=One-Click"
    # Compliance defaults: never bypass the global block / unsubscribe lists.
    assert body["settings"]["ignore_global_block_list"] is False
    assert body["settings"]["ignore_unsubscribe_list"] is False

    # (c) success maps to accepted=True with a lead id.
    assert result.accepted is True
    assert result.provider_message_id == "4242"
    assert result.provider_name == "smartlead"
    assert result.error is None


def test_non_2xx_degrades_to_not_accepted(monkeypatch):
    def fake_post(self, url, *, params=None, json=None, **kwargs):
        return _Resp(raise_status=True)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = SmartleadSendingProvider("key").send(_message())
    assert result.accepted is False
    assert result.provider_message_id is None
    assert result.provider_name == "smartlead"
    assert result.error


def test_transport_error_degrades_without_raising(monkeypatch):
    def fake_post(self, url, *, params=None, json=None, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = SmartleadSendingProvider("key").send(_message())
    assert result.accepted is False
    assert result.error


def test_unexpected_response_shape_degrades(monkeypatch):
    # A list instead of a dict must not crash — it degrades to not-accepted.
    def fake_post(self, url, *, params=None, json=None, **kwargs):
        return _Resp(json_value=["surprise"])

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = SmartleadSendingProvider("key").send(_message())
    assert result.accepted is False
    assert result.error


def test_lead_ref_fallback_when_no_id(monkeypatch):
    # No lead id in the response → stable {campaign_id}:{email} reference.
    def fake_post(self, url, *, params=None, json=None, **kwargs):
        return _Resp(json_value={"success": True, "upload_count": 1})

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = SmartleadSendingProvider("key").send(_message())
    assert result.accepted is True
    assert result.provider_message_id == "camp-123:buyer@acme.example"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])

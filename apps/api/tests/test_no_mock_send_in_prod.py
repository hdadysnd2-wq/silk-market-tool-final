"""Regression locks: no silent mock-sender fallback outside local (Wave 2 item 4).

With no SMARTLEAD_API_KEY the registry fell back to the mock sender in every
environment, and the mock returns accepted=True — so a misconfigured production
deploy marked emails ``sent`` that never left the building, incremented
campaign counters, and wrote send audit records. Outside ``local`` the slot now
fails closed (GatedSendingProvider / GatedMailboxProvider) unless the operator
explicitly opts into mocks with ALLOW_MOCK_SENDING=1.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.models import EmailStatus
from app.providers.registry import get_mailbox_provider, get_sending_provider
from app.providers.sending.mock import MockMailboxProvider, MockSendingProvider
from app.services import approval
from app.services.sending import SendBlocked, send_email
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _prod_settings(**overrides) -> Settings:
    return Settings(
        environment="production",
        secret_key="a-strong-production-secret-key-32-bytes!",
        token_encryption_key=Fernet.generate_key().decode(),
        # Safe prod networking defaults (audit H7) — required now that the
        # config fails closed on trusted_proxy_count=0 / localhost api_base_url.
        trusted_proxy_count=1,
        api_base_url="https://api.silk.example",
        app_base_url="https://app.silk.example",
        **overrides,
    )


def test_prod_without_provider_gets_gated_sender():
    provider = get_sending_provider(_prod_settings())
    assert "gated" in provider.name
    result = provider.send(_message())
    assert result.accepted is False
    assert "ALLOW_MOCK_SENDING" in (result.error or "")


def test_prod_with_explicit_opt_in_gets_mock():
    provider = get_sending_provider(_prod_settings(allow_mock_sending=True))
    assert isinstance(provider, MockSendingProvider)


def test_local_keeps_the_mock():
    settings = Settings(environment="local")
    assert isinstance(get_sending_provider(settings), MockSendingProvider)
    assert isinstance(get_mailbox_provider("gmail", settings), MockMailboxProvider)


def test_prod_mailbox_slot_is_gated_without_oauth_app():
    provider = get_mailbox_provider("gmail", _prod_settings())
    assert "gated" in provider.name
    result = provider.send(None, _message())
    assert result.accepted is False
    with pytest.raises(RuntimeError, match="ALLOW_MOCK_SENDING"):
        provider.authorization_url(state="s", redirect_uri="https://x/cb")
    assert provider.fetch_replies(None, None) == []


def test_gated_send_keeps_email_queued_never_sent(db, factory, product, admin_user):
    buyer, contact = make_buyer_with_contact(db, email="buyer@acme.example.in")
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    db.commit()

    gated = get_sending_provider(_prod_settings())
    with pytest.raises(SendBlocked):
        send_email(db, email.id, gated)

    db.expire_all()
    refreshed_status = db.get(type(email), email.id).status
    assert refreshed_status == EmailStatus.queued
    assert campaign.sent_count == 0


def _message():
    from app.providers.base import OutboundEmail

    return OutboundEmail(
        to_email="someone@example.com",
        to_name="Someone",
        subject="s",
        body_text="b",
        body_html="<p>b</p>",
        from_name="Silk",
        from_email="silk@example.com",
        reply_to=None,
        sending_domain=None,
        unsubscribe_url="https://x/u/t",
        campaign_ref="c-1",
        message_ref="t-1",
    )

"""The Smartlead cold-send slot fails closed until its sequence is verified.

``SMARTLEAD_API_KEY`` alone flips every other kind of slot live, but the one-click
List-Unsubscribe headers RFC 8058 / I4 require are emitted by the Smartlead
*campaign sequence template*, not by our adapter — a console step no offline test
can observe. So a key without ``SMARTLEAD_SEQUENCE_VERIFIED`` must NOT produce a
sender that can put mail on the wire.

Offline and DB-free: the registry is driven with explicit ``Settings`` objects and
no HTTP client is ever constructed (the gate refuses before any network call).
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.models import EmailStatus
from app.providers.base import OutboundEmail
from app.providers.registry import get_sending_provider
from app.providers.sending.gated import GatedSendingProvider
from app.providers.sending.mock import MockSendingProvider
from app.providers.sending.smartlead import SmartleadSendingProvider
from app.services import approval
from app.services.sending import SendBlocked, send_email
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _settings(**overrides) -> Settings:
    base = {
        "secret_key": "test-secret-key-at-least-32-bytes-long-000",
        "environment": "local",
    }
    return Settings(**{**base, **overrides})


def _message() -> OutboundEmail:
    return OutboundEmail(
        to_email="buyer@acme.example",
        to_name="Ada Lovelace",
        subject="Saudi dates for your shelves",
        body_text="Hello Ada,",
        body_html="<p>Hello Ada,</p>",
        from_name="Silk Outreach",
        from_email="outreach@silk.example",
        reply_to="sales@silk.example",
        sending_domain="silk.example",
        unsubscribe_url="https://silk.example/u/tok123",
        campaign_ref="camp-123",
        message_ref="msg-9",
    )


def test_no_key_still_selects_the_mock():
    """The gate must not disturb the offline default: no key → mock, as before."""
    provider = get_sending_provider(_settings(smartlead_api_key=""))
    assert isinstance(provider, MockSendingProvider)


def test_key_without_verified_sequence_is_gated_not_live():
    provider = get_sending_provider(_settings(smartlead_api_key="sk-live-xxx"))
    assert isinstance(provider, GatedSendingProvider)
    assert not isinstance(provider, SmartleadSendingProvider)
    # /health must show the gated state rather than claiming a live Smartlead.
    assert provider.name == "smartlead (gated)"


def test_gated_provider_refuses_every_send_with_an_actionable_reason():
    provider = get_sending_provider(_settings(smartlead_api_key="sk-live-xxx"))
    result = provider.send(_message())
    assert result.accepted is False
    assert result.provider_message_id is None
    # The operator gets the exact unblock step, not a bare failure.
    assert "SMARTLEAD_SEQUENCE_VERIFIED" in (result.error or "")


def test_verified_sequence_selects_the_real_adapter():
    provider = get_sending_provider(
        _settings(smartlead_api_key="sk-live-xxx", smartlead_sequence_verified=True)
    )
    assert isinstance(provider, SmartleadSendingProvider)


def test_verified_flag_alone_never_goes_live_without_a_key():
    """The flag is a confirmation, not a switch — no key still means the mock."""
    provider = get_sending_provider(_settings(smartlead_sequence_verified=True))
    assert isinstance(provider, MockSendingProvider)


def test_gated_slot_blocks_a_fully_approved_email_and_leaves_it_queued(
    db, factory, product, admin_user
):
    """The gate holds at the real send path, not just at provider construction.

    An email that cleared every human gate (approved → queued) still must not go
    out through a gated slot: ``send_email`` raises ``SendBlocked`` and the row
    stays ``queued``, so nothing is lost and the send can be retried the moment
    the sequence is verified.
    """
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    db.commit()

    provider = get_sending_provider(_settings(smartlead_api_key="sk-live-xxx"))
    with pytest.raises(SendBlocked, match="SMARTLEAD_SEQUENCE_VERIFIED"):
        send_email(db, email.id, provider)

    db.refresh(email)
    assert email.status == EmailStatus.queued
    assert email.sent_at is None
    assert email.provider_message_id is None

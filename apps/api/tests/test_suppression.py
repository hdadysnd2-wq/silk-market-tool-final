"""Suppression ledger — a hard pre-send block, honored across all campaigns."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models import EmailStatus, SuppressionReason
from app.providers.base import SendResult
from app.services import approval, suppression
from app.services.sending import record_engagement, send_email
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def test_unsubscribe_adds_suppression_and_cancels_pending(db, factory, product, admin_user):
    buyer, contact = make_buyer_with_contact(db, email="opt-out@acme.example.in")
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    suppression.suppress(db, email=contact.email, reason=SuppressionReason.unsubscribe)
    db.commit()

    assert suppression.is_suppressed(db, contact.email)
    db.refresh(email)
    # The pending draft to this address is cancelled.
    assert email.status == EmailStatus.cancelled


def test_queue_blocked_for_suppressed_contact(db, factory, product, admin_user):
    buyer, contact = make_buyer_with_contact(db, email="blocked@acme.example.in")
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    approval.approve(db, email, admin_user)
    # Suppress a *different* representation to prove normalization; same address.
    suppression.suppress(db, email="BLOCKED@acme.example.in", reason=SuppressionReason.manual)

    with pytest.raises(approval.TransitionError):
        approval.queue(db, email, admin_user)

    db.refresh(email)
    assert email.status == EmailStatus.blocked_suppressed


def test_send_task_blocks_suppression_added_after_queue(db, factory, product, admin_user):
    """The race the spec calls out: suppressed *after* queueing, blocked at send."""
    buyer, contact = make_buyer_with_contact(db, email="late@acme.example.in")
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    db.commit()

    # Now the recipient opts out, between queueing and the worker running.
    suppression.suppress(db, email=contact.email, reason=SuppressionReason.unsubscribe)
    db.commit()

    spy = MagicMock()
    result = send_email(db, email.id, spy)
    spy.send.assert_not_called()
    assert result.status == EmailStatus.blocked_suppressed


def test_suppression_spans_campaigns(db, factory, product, admin_user):
    """One unsubscribe silences the address in a second campaign too."""
    buyer, contact = make_buyer_with_contact(db, email="global@acme.example.in")
    campaign_a = make_campaign(db, factory, product)
    campaign_b = make_campaign(db, factory, product)
    email_a = make_draft_email(db, campaign_a, buyer, contact)
    email_b = make_draft_email(db, campaign_b, buyer, contact)

    # email_b is already approved before the opt-out arrives; email_a is a draft.
    approval.approve(db, email_b, admin_user)

    suppression.suppress(db, email=contact.email, reason=SuppressionReason.unsubscribe)
    db.commit()

    # The draft in campaign A was cancelled outright by the opt-out.
    db.refresh(email_a)
    assert email_a.status == EmailStatus.cancelled

    # The approved email in campaign B is blocked at the gate — proving the
    # suppression spans campaigns.
    with pytest.raises(approval.TransitionError):
        approval.queue(db, email_b, admin_user)
    db.refresh(email_b)
    assert email_b.status == EmailStatus.blocked_suppressed


def test_bounce_webhook_adds_suppression(db, factory, product, admin_user):
    buyer, contact = make_buyer_with_contact(db, email="bouncy@acme.example.in")
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    provider = MagicMock()
    provider.send.return_value = SendResult(
        accepted=True, provider_message_id="msg-b1", provider_name="mock"
    )
    send_email(db, email.id, provider)
    db.commit()

    record_engagement(db, "msg-b1", "bounced", bounce_type="hard")
    db.commit()

    assert suppression.is_suppressed(db, contact.email)
    db.refresh(email)
    assert email.status == EmailStatus.bounced


def test_is_suppressed_false_for_clean_address(db):
    assert not suppression.is_suppressed(db, "clean@example.com")

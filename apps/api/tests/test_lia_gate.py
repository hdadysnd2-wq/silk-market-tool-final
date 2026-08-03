"""I8 — the EU Legitimate Interest Assessment gate.

An email to an EU market cannot be queued until a LIA is on file, and the
campaign serializer surfaces that state to the approval UI so the operator can
record one instead of hitting a dead end.
"""

from __future__ import annotations

import pytest

from app.api.campaigns import _campaign_out
from app.models import EmailStatus, LIARecord, utcnow
from app.services import approval
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _record_lia(db, campaign, user):
    db.add(
        LIARecord(
            campaign_id=campaign.id,
            purpose_text="Offer Saudi dates to an EU importer already trading the category.",
            necessity_text="Direct B2B contact is the only way to open a trade conversation.",
            balancing_test_text="Business contact, relevant offer, easy opt-out.",
            data_sources="Public import records",
            completed_by=user.id,
            completed_at=utcnow(),
        )
    )
    db.flush()


def test_serializer_flags_eu_and_lia(db, factory, product, admin_user, eu_market):
    """The campaign serializer tells the UI a LIA is required, and when it lands."""
    campaign = make_campaign(db, factory, product, market_iso2="DE")

    out = _campaign_out(db, campaign)
    assert out.market_is_eu is True
    assert out.lia_recorded is False

    _record_lia(db, campaign, admin_user)
    assert _campaign_out(db, campaign).lia_recorded is True


def test_non_eu_campaign_needs_no_lia(db, factory, product, market):
    campaign = make_campaign(db, factory, product, market_iso2="IN")
    out = _campaign_out(db, campaign)
    assert out.market_is_eu is False


def test_eu_email_blocked_from_queue_without_lia(db, factory, product, admin_user, eu_market):
    """Even an approved EU-market email cannot be queued until a LIA exists."""
    buyer, contact = make_buyer_with_contact(db, market_iso2="DE", email="buyer@acme.example.de")
    campaign = make_campaign(db, factory, product, market_iso2="DE")
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)

    with pytest.raises(approval.TransitionError):
        approval.queue(db, email, admin_user)

    db.refresh(email)
    assert email.status == EmailStatus.approved  # still gated, not queued


def test_eu_email_queues_after_lia(db, factory, product, admin_user, eu_market):
    """With a LIA on file the same email clears the gate and queues."""
    buyer, contact = make_buyer_with_contact(db, market_iso2="DE", email="buyer@acme.example.de")
    campaign = make_campaign(db, factory, product, market_iso2="DE")
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    _record_lia(db, campaign, admin_user)

    queued = approval.queue(db, email, admin_user)
    assert queued.status == EmailStatus.queued

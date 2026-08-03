"""Phase 4 — PDPL retention (data minimisation) and erasure (right to be forgotten).

Personal data is anonymised in place, never hard-deleted (that would cascade the
send record away). The append-only audit log is preserved, and an erased subject
stays on the global suppression ledger.
"""

from __future__ import annotations

from datetime import timedelta

from app.models import AuditLog, utcnow
from app.services import retention, suppression
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _backdate(db, contact, days):
    contact.created_at = utcnow() - timedelta(days=days)
    db.flush()


def test_retention_anonymises_stale_contact(db):
    _buyer, contact = make_buyer_with_contact(db, email="old.lead@example.in")
    contact.full_name = "Jane Buyer"
    _backdate(db, contact, 400)

    anonymised = retention.purge_stale_pii(db, retention_days=180)

    assert anonymised == 1
    db.refresh(contact)
    assert contact.email.endswith("@pdpl.invalid")
    assert contact.full_name is None
    assert retention.is_anonymised(contact)
    assert db.query(AuditLog).filter(AuditLog.action == "pdpl_retention_anonymise").count() == 1


def test_retention_keeps_recent_contact(db):
    _buyer, contact = make_buyer_with_contact(db, email="fresh.lead@example.in")
    _backdate(db, contact, 10)

    anonymised = retention.purge_stale_pii(db, retention_days=180)

    assert anonymised == 0
    db.refresh(contact)
    assert contact.email == "fresh.lead@example.in"


def test_retention_keeps_stale_contact_with_live_draft(db, factory, product):
    """A contact still being worked (a live draft) is never anonymised, however old."""
    buyer, contact = make_buyer_with_contact(db, email="working.lead@example.in")
    _backdate(db, contact, 400)
    campaign = make_campaign(db, factory, product)
    make_draft_email(db, campaign, buyer, contact)

    anonymised = retention.purge_stale_pii(db, retention_days=180)

    assert anonymised == 0
    db.refresh(contact)
    assert contact.email == "working.lead@example.in"


def test_erasure_anonymises_and_suppresses(db):
    _buyer, contact = make_buyer_with_contact(db, email="forget.me@example.in")
    contact.full_name = "Forgotten Person"
    db.flush()

    # Case-insensitive: the request address need not match the stored casing.
    erased = retention.erase_data_subject(db, email="Forget.Me@example.IN")

    assert erased == 1
    db.refresh(contact)
    assert contact.email.endswith("@pdpl.invalid")
    assert contact.full_name is None
    assert suppression.is_suppressed(db, "forget.me@example.in")
    assert db.query(AuditLog).filter(AuditLog.action == "pdpl_erasure_request").count() == 1


def test_erasure_of_unknown_address_still_suppresses(db):
    """A request for an address we hold no contact for still lands a durable
    suppression, so a later re-import can never reach them."""
    erased = retention.erase_data_subject(db, email="nobody@example.in")

    assert erased == 0
    assert suppression.is_suppressed(db, "nobody@example.in")

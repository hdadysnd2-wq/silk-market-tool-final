"""Enforcing tests for two hard invariants that previously had none (D5 / HIGH-15).

* I3 — the send worker re-reads the row under a lock and re-verifies status at
  send time, so an email whose status changed after the API queued it (a
  concurrent cancel, or another worker that already claimed it) is never sent.
* I4 — suppression is GLOBAL: an address suppressed via one factory (tenant) is
  blocked for a *different* factory sending to the same address.

Each test is written to FAIL if its guard is removed:
  * I3 — comment out the ``status != queued`` re-check in ``sending.send_email``
    and the flipped email would send (``provider.send`` would be called).
  * I4 — comment out the suppression re-check (re-check 3) and tenant B's send
    would go out to the suppressed address.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.db import SessionLocal
from app.models import Email, EmailStatus, Factory, Product, SuppressionReason, utcnow
from app.services import approval, suppression
from app.services.sending import SendBlocked, send_email
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _factory(db, name_en: str, domain: str) -> Factory:
    f = Factory(
        name_ar=name_en,
        name_en=name_en,
        sector="food",
        city="Riyadh",
        contact_person="Owner",
        contact_email=f"owner@{domain}",
        postal_address="Riyadh, Saudi Arabia",
        sending_domain=domain,
        spf_ok=True,
        dkim_ok=True,
        dmarc_ok=True,
        warmup_started_at=utcnow(),
        warmup_day=14,
    )
    db.add(f)
    db.commit()
    return f


def _product(db, factory: Factory) -> Product:
    p = Product(
        factory_id=factory.id,
        name_ar="منتج",
        name_en="Product",
        description_en="A product",
        hs_code=None,  # irrelevant to the send/suppression path; avoids the HSCode FK
        currency="USD",
        price_min=100,
        price_max=200,
    )
    db.add(p)
    db.commit()
    return p


# ── I3 — worker row-lock re-check at send time ──────────────────────────────


def test_i3_worker_refuses_to_send_when_status_flipped_after_queue(
    db, factory, product, admin_user
):
    buyer, contact = make_buyer_with_contact(db, email="race@acme.example.in")
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    db.commit()

    # Between queue and worker pickup, another session flips the status (an admin
    # cancels it / another worker already claimed the row).
    other = SessionLocal()
    try:
        row = other.get(Email, email.id)
        row.status = EmailStatus.cancelled
        other.commit()
    finally:
        other.close()
    db.expire_all()

    provider = MagicMock()
    with pytest.raises(SendBlocked):
        send_email(db, email.id, provider)  # re-reads under lock, sees cancelled
    provider.send.assert_not_called()  # never reaches egress


# ── I4 — suppression is cross-tenant (global) ───────────────────────────────


def test_i4_suppression_blocks_a_different_tenant(db, factory, product, admin_user):
    shared = "shared@buyer.example.in"
    buyer, contact = make_buyer_with_contact(db, email=shared)

    # Tenant A (the `factory` fixture) has an email to the shared address.
    email_a = make_draft_email(db, make_campaign(db, factory, product), buyer, contact)

    # Tenant B — a DIFFERENT factory — has an approved, queued email to the SAME
    # address (queued before the opt-out arrives).
    factory_b = _factory(db, "Tenant B Foods", "tenant-b-export.example")
    product_b = _product(db, factory_b)
    email_b = make_draft_email(db, make_campaign(db, factory_b, product_b), buyer, contact)
    approval.approve(db, email_b, admin_user)
    approval.queue(db, email_b, admin_user)
    db.commit()

    # Tenant A's recipient unsubscribes → one global ledger entry.
    suppression.suppress(
        db,
        email=shared,
        reason=SuppressionReason.unsubscribe,
        source_email_id=email_a.id,
    )
    db.commit()

    # Tenant B's send is blocked by tenant A's suppression (I4 is global).
    provider = MagicMock()
    result = send_email(db, email_b.id, provider)
    provider.send.assert_not_called()
    assert result.status == EmailStatus.blocked_suppressed

"""Enforcing tests for invariants that previously held only by construction.

Closes the four gaps the 2026-08-05 conformance audit named:
I4 cross-*tenant* suppression, the complaint-rate auto-pause threshold,
I8 "no bulk lead export" (absence of any export route), and the I3 approval
gate exercised at the HTTP boundary rather than only at the service layer.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.main import app
from app.models import CampaignStatus, EmailStatus, Factory, Product, SuppressionReason, utcnow
from app.services import approval, deliverability, suppression
from app.services.sending import send_email
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _second_factory_with_product(db) -> tuple[Factory, Product]:
    f = Factory(
        name_ar="مصنع ثانٍ",
        name_en="Second Factory",
        sector="food",
        city="Riyadh",
        contact_person="Owner Two",
        contact_email="owner@secondfactory-export.com",
        postal_address="Riyadh, Saudi Arabia",
        sending_domain="secondfactory-export.com",
        spf_ok=True,
        dkim_ok=True,
        dmarc_ok=True,
        warmup_started_at=utcnow(),
        warmup_day=14,
    )
    db.add(f)
    db.flush()
    p = Product(
        factory_id=f.id,
        name_ar="منتج",
        name_en="Second Product",
        hs_code="392010",
        hs_confirmed_by_user=True,
        classification_status="classified",
        currency="USD",
    )
    db.add(p)
    db.commit()
    return f, p


def test_suppression_is_cross_tenant(db, factory, product, admin_user):
    """I4 — an address suppressed via ANY tenant blocks every other tenant's send."""
    other_factory, other_product = _second_factory_with_product(db)
    buyer, contact = make_buyer_with_contact(db, email="shared@buyer.example.in")
    campaign = make_campaign(db, other_factory, other_product)
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)

    # Suppressed in the context of the FIRST factory (unsubscribe from its mail);
    # the ledger keys on the address alone, so the second tenant is blocked too.
    suppression.suppress(
        db,
        email=contact.email,
        reason=SuppressionReason.unsubscribe,
        actor_label=f"factory:{factory.id}",
    )
    db.commit()

    spy = MagicMock()
    result = send_email(db, email.id, spy)
    spy.send.assert_not_called()
    assert result.status == EmailStatus.blocked_suppressed


def test_auto_pause_on_high_complaint_rate(db, factory, product):
    """Complaint rate above 0.1% must auto-pause the campaign (spec threshold)."""
    campaign = make_campaign(db, factory, product)
    campaign.status = CampaignStatus.active
    campaign.sent_count = 1000
    campaign.complained_count = 2  # 0.2% > 0.1% threshold
    db.commit()

    paused = deliverability.evaluate_campaign_health(db, campaign)
    assert paused
    assert campaign.status == CampaignStatus.auto_paused
    assert "complaint" in campaign.paused_reason


def test_no_bulk_export_route_exists():
    """I8 — leads must never be bulk-exportable outside the analysis context.

    Locks the absence of any export/CSV/dump surface: if someone adds one, this
    fails and forces the compliance conversation instead of shipping silently.
    """
    forbidden = ("export", "csv", "dump", "download")
    offenders = [
        route.path
        for route in app.routes
        if any(token in route.path.lower() for token in forbidden)
    ]
    assert offenders == [], f"bulk-export-shaped routes found: {offenders}"


def test_queue_draft_rejected_at_http_boundary(client, db, factory, product, factory_user):
    """I3 layer (a) — the HTTP API itself refuses to queue an unapproved draft."""
    from app.security import create_access_token

    buyer, contact = make_buyer_with_contact(db, email="draft@buyer.example.in")
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    headers = {"Authorization": f"Bearer {create_access_token(factory_user.id, factory_user.role)}"}
    res = client.post(f"/api/v1/emails/{email.id}/queue", headers=headers)
    assert res.status_code in (400, 409), res.text
    db.refresh(email)
    assert email.status == EmailStatus.draft  # untouched — never queued

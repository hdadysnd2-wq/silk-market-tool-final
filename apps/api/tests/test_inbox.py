"""GET /inbox — unified cross-campaign replies list, tenant-scoped."""

from __future__ import annotations

from datetime import timedelta

from app.models import EmailStatus, Factory, Product, utcnow
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _mark_replied(db, email, *, minutes_ago: int) -> None:
    now = utcnow()
    # The DB approval gate keys on approved_at — a sent-family status without it
    # would violate the CHECK constraint.
    email.approved_at = now - timedelta(minutes=minutes_ago + 5)
    email.status = EmailStatus.replied
    email.sent_at = now - timedelta(minutes=minutes_ago + 2)
    email.replied_at = now - timedelta(minutes=minutes_ago)
    db.commit()


def test_inbox_lists_only_replied_newest_first(client, db, factory, product, auth_headers):
    campaign = make_campaign(db, factory, product)
    b1, c1 = make_buyer_with_contact(db, market_iso2="IN", email="a@buyer.example.in")
    b2, c2 = make_buyer_with_contact(db, market_iso2="AE", email="b@buyer.example.ae")
    older = make_draft_email(db, campaign, b1, c1)
    newer = make_draft_email(db, campaign, b2, c2)
    still_draft = make_draft_email(db, campaign, b1, c1)
    _mark_replied(db, older, minutes_ago=60)
    _mark_replied(db, newer, minutes_ago=5)

    res = client.get("/api/v1/inbox", headers=auth_headers)
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [r["email_id"] for r in rows] == [str(newer.id), str(older.id)]
    assert str(still_draft.id) not in {r["email_id"] for r in rows}
    top = rows[0]
    assert top["campaign_name"] == "Test Campaign"
    assert top["buyer_name"] == "Acme Importers"
    assert top["contact_email"] == "b@buyer.example.ae"
    assert top["replied_at"] is not None


def test_inbox_is_tenant_scoped(client, db, factory, product, auth_headers):
    # A reply that belongs to a DIFFERENT factory must never appear.
    other = Factory(
        name_ar="مصنع آخر",
        name_en="Other Factory",
        sector="food",
        city="Riyadh",
        contact_person="Owner",
        contact_email="owner@otherfactory-export.com",
        postal_address="Riyadh, Saudi Arabia",
        sending_domain="otherfactory-export.com",
        spf_ok=True,
        dkim_ok=True,
        dmarc_ok=True,
        warmup_started_at=utcnow(),
        warmup_day=14,
    )
    db.add(other)
    db.flush()
    other_product = Product(
        factory_id=other.id,
        name_ar="منتج",
        name_en="Other Product",
        hs_code="392010",
        hs_confirmed_by_user=True,
        classification_status="classified",
        currency="USD",
    )
    db.add(other_product)
    db.commit()
    foreign = make_campaign(db, other, other_product, market_iso2="AE")
    b, c = make_buyer_with_contact(db, market_iso2="AE", email="x@buyer.example.ae")
    email = make_draft_email(db, foreign, b, c)
    _mark_replied(db, email, minutes_ago=1)

    res = client.get("/api/v1/inbox", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json() == []

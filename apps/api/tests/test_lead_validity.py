"""Lead validity window (rule 6 / I8): 90-day stamp + explicit stale warning.

A discovered buyer is current for 90 days; past that its listing must flag the
data as stale so a human never treats an old lead as fresh. Unknown freshness is
treated as stale (the conservative default).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import Buyer, utcnow
from app.services import lead_validity
from app.services.buyer_discovery import discover_buyers


def test_fresh_lead_is_valid_and_not_stale():
    now = utcnow()
    until = lead_validity.valid_until(now)
    assert until == now + timedelta(days=lead_validity.LEAD_VALIDITY_DAYS)
    assert lead_validity.is_stale(now) is False


def test_lead_past_the_window_is_stale():
    old = utcnow() - timedelta(days=lead_validity.LEAD_VALIDITY_DAYS + 1)
    assert lead_validity.is_stale(old) is True


def test_unknown_freshness_is_treated_as_stale():
    assert lead_validity.valid_until(None) is None
    assert lead_validity.is_stale(None) is True


def test_buyers_listing_stamps_validity(client, auth_headers, db, factory, product, market):
    discover_buyers(db, product, "IN")
    db.commit()

    res = client.get(f"/api/v1/products/{product.id}/buyers?market=IN", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body, "discovery seeded at least one buyer"

    for match in body:
        buyer = match["buyer"]
        # Freshly discovered → stamped valid, explicitly not stale.
        assert buyer["freshness_at"] is not None
        assert buyer["valid_until"] is not None
        assert buyer["is_stale"] is False


def test_stale_buyer_is_flagged_in_listing(client, auth_headers, db, factory, product, market):
    discover_buyers(db, product, "IN")
    # Age every discovered buyer past the 90-day window.
    for buyer in db.scalars(select(Buyer)):
        buyer.freshness_at = utcnow() - timedelta(days=lead_validity.LEAD_VALIDITY_DAYS + 5)
    db.commit()

    res = client.get(f"/api/v1/products/{product.id}/buyers?market=IN", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body
    assert all(match["buyer"]["is_stale"] is True for match in body)

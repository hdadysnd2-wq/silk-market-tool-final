"""Observed competitor prices — the deepen-gated paid layer (Wave 3, I5 + I2).

Prices are fetched only inside the deepen scope (I5) and only on a human-confirmed
HS code (I2). Every price is an observed listing with its source, persisted onto
the market snapshot; nothing is fabricated.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import MarketSnapshot
from app.providers.pricing.mock import MockPriceProvider
from app.services import observed_prices


def test_mock_price_provider_is_deterministic():
    a = MockPriceProvider().observed_prices("392010", "IN")
    b = MockPriceProvider().observed_prices("392010", "IN")
    assert a and [r.data.competitor for r in a] == [r.data.competitor for r in b]
    assert [r.data.price for r in a] == [r.data.price for r in b]
    for r in a:
        assert r.data.price > 0 and r.data.url  # observed listing with a source link


def test_price_fetch_is_refused_outside_deepen(db, factory, product):
    # I5 — the paid layer must not run outside the deepen scope; no provider call,
    # no persisted prices.
    result = observed_prices.fetch_prices_for_market(db, product, "IN")
    assert result["skipped"] is True
    assert result["reason"] == observed_prices.SKIPPED_OUTSIDE_DEEPEN
    assert result["count"] == 0

    snap = db.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.hs_code == product.hs_code, MarketSnapshot.market_iso2 == "IN"
        )
    )
    assert snap is None or not snap.observed_prices


def test_deepen_prices_endpoint_persists_prices(client, auth_headers, db, factory, product):
    res = client.post(
        f"/api/v1/products/{product.id}/deepen/prices",
        headers=auth_headers,
        json={"markets": ["IN"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["results"][0]["skipped"] is False
    assert body["results"][0]["count"] > 0

    snap = db.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.hs_code == product.hs_code, MarketSnapshot.market_iso2 == "IN"
        )
    )
    assert snap is not None and snap.observed_prices
    first = snap.observed_prices[0]
    assert first["competitor"] and first["price"] > 0 and first["source"]


def test_deepen_prices_requires_confirmed_hs(client, auth_headers, db, factory, product):
    # I2 — the paid layer runs only on a human-confirmed HS code.
    product.hs_confirmed_by_user = False
    db.commit()

    res = client.post(
        f"/api/v1/products/{product.id}/deepen/prices",
        headers=auth_headers,
        json={"markets": ["IN"]},
    )
    assert res.status_code == 409

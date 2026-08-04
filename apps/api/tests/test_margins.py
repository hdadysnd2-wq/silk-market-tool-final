"""Margin threads — the factory's margin against each competitor's observed price.

Wave 3 part 2. A margin is computed only where a competitor price AND the product's
cost are known; otherwise the thread declares the gap rather than inventing a
figure (I1).
"""

from __future__ import annotations

from app.models import MarketSnapshot
from app.services.margins import compute_margin_threads


def _snapshot_with_prices(db, hs_code, iso2="IN"):
    db.add(
        MarketSnapshot(
            hs_code=hs_code,
            market_iso2=iso2,
            source="comtrade",
            observed_prices=[
                {
                    "competitor": "Alahlia Foods",
                    "price": 20.0,
                    "currency": "USD",
                    "url": "http://x/a",
                },
                {
                    "competitor": "Gulf Pantry",
                    "price": 30.0,
                    "currency": "USD",
                    "url": "http://x/g",
                },
            ],
        )
    )
    db.commit()


def test_margins_computed_when_price_and_cost_exist(db, factory, product):
    product.cost_per_unit = 12.0
    _snapshot_with_prices(db, product.hs_code)

    out = compute_margin_threads(db, product, "IN")

    assert out["cost_available"] is True
    assert len(out["competitor_threads"]) == 2
    assert all(t["observed_price"] for t in out["competitor_threads"])

    by_name = {m["competitor"]: m["margin_at_match_pct"] for m in out["margin_threads"]}
    assert by_name["Alahlia Foods"] == 40.0  # (20 - 12) / 20
    assert by_name["Gulf Pantry"] == 60.0  # (30 - 12) / 30


def test_margin_is_a_declared_gap_without_cost(db, factory, product):
    product.cost_per_unit = None
    _snapshot_with_prices(db, product.hs_code)

    out = compute_margin_threads(db, product, "IN")

    assert out["cost_available"] is False
    assert out["competitor_threads"]  # observed prices are still surfaced
    assert out["margin_threads"] == []  # I1 — no fabricated margin
    assert out["note"]


def test_margins_endpoint_returns_threads(client, auth_headers, db, factory, product):
    product.cost_per_unit = 12.0
    _snapshot_with_prices(db, product.hs_code)

    res = client.get(f"/api/v1/products/{product.id}/margins?market=IN", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["cost_available"] is True
    assert body["margin_threads"]

"""Competitor margin thread — name + observed price + computed margin (DoD).

Derived with zero external calls from the factory's offer and the observed prices
the deepen layer persisted. Every margin is computed or a declared gap (I1): no
offer price, a currency mismatch, or no observed prices yields None + a note,
never a fabricated margin.
"""

from __future__ import annotations

from app.models import MarketSnapshot, Product
from app.services.margin import build_margin_thread


def _fetch_prices(client, auth_headers, product, market="IN"):
    res = client.post(
        f"/api/v1/products/{product.id}/deepen/prices",
        headers=auth_headers,
        json={"markets": [market]},
    )
    assert res.status_code == 200, res.text


def test_margin_thread_computes_from_observed_prices(client, auth_headers, db, factory, product):
    _fetch_prices(client, auth_headers, product)

    res = client.get(f"/api/v1/products/{product.id}/markets/IN/margin", headers=auth_headers)
    assert res.status_code == 200, res.text
    thread = res.json()

    assert thread["market_iso2"] == "IN"
    assert thread["factory_offer"] == 1400.0  # midpoint of the fixture's 1200–1600
    assert thread["factory_currency"] == "USD"
    assert thread["competitors"]  # observed prices were fetched
    # Each USD listing gets a computed margin (name + observed price + margin).
    for c in thread["competitors"]:
        assert c["competitor"]
        assert c["observed_price"] is not None
        assert c["margin_pct"] is not None
    assert thread["median_margin_pct"] is not None
    # The source line and the honest "gross headroom" limit are always present.
    assert thread["source_line"]
    assert any("Gross headroom" in limit for limit in thread["limits"])


def test_margin_thread_declares_gap_without_observed_prices(client, auth_headers, product):
    # No deepen fetch has run → no observed prices; the thread declares the gap
    # rather than erroring or inventing a margin.
    res = client.get(f"/api/v1/products/{product.id}/markets/IN/margin", headers=auth_headers)
    assert res.status_code == 200, res.text
    thread = res.json()
    assert thread["competitors"] == []
    assert thread["median_margin_pct"] is None
    assert any("No observed competitor prices" in limit for limit in thread["limits"])


def test_margin_thread_declares_gap_without_offer_price(client, auth_headers, db, product):
    # A product with no price band → margins cannot be computed; each competitor is
    # a declared gap and the limit says why.
    product.price_min = None
    product.price_max = None
    db.commit()
    _fetch_prices(client, auth_headers, product)

    thread = client.get(
        f"/api/v1/products/{product.id}/markets/IN/margin", headers=auth_headers
    ).json()
    assert thread["factory_offer"] is None
    assert thread["competitors"]  # prices exist…
    assert all(c["margin_pct"] is None for c in thread["competitors"])  # …but no margin
    assert all("no factory offer price" in c["note"] for c in thread["competitors"])
    assert any("No factory offer price" in limit for limit in thread["limits"])


def test_margin_service_treats_currency_mismatch_as_a_gap(db, factory, product):
    # A EUR observed price against a USD offer must not invent an FX rate (I1).
    product.currency = "USD"
    snapshot = MarketSnapshot(
        hs_code=product.hs_code,
        market_iso2="DE",
        source="localprice_mock",
        observed_prices=[
            {"competitor": "Cedar & Co", "price": 20.0, "currency": "EUR", "source": "x"},
            {"competitor": "Gulf Pantry", "price": 25.0, "currency": "USD", "source": "x"},
        ],
    )
    thread = build_margin_thread(product, "DE", snapshot)
    by_name = {c["competitor"]: c for c in thread["competitors"]}
    assert by_name["Cedar & Co"]["margin_pct"] is None
    assert "currency mismatch" in by_name["Cedar & Co"]["note"]
    assert by_name["Gulf Pantry"]["margin_pct"] is not None  # USD one still computes
    assert any("currency" in limit for limit in thread["limits"])


def test_offer_midpoint_handles_partial_band(db, factory):
    # Only a min price on file → the offer is that value, not an averaged gap.
    p = Product(
        factory_id=factory.id,
        name_ar="x",
        name_en="x",
        hs_code=None,
        price_min=10.0,
        price_max=None,
        currency="USD",
    )
    thread = build_margin_thread(p, "IN", None)
    assert thread["factory_offer"] == 10.0

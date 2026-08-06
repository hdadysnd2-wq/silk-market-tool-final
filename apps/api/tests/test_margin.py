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
    assert thread["margin_basis"] is None  # neither cost nor offer on file
    assert thread["competitors"]  # prices exist…
    assert all(c["margin_pct"] is None for c in thread["competitors"])  # …but no margin
    assert all("no factory cost or offer price" in c["note"] for c in thread["competitors"])
    assert any("No factory cost or offer price" in limit for limit in thread["limits"])


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


def test_margin_prefers_real_cost_over_offer_estimate(db, factory, product):
    # A recorded per-unit cost (800) makes the margin a REAL gross margin against
    # cost, not headroom vs the 1400 offer midpoint. The offer is still surfaced
    # for context but is not the basis.
    product.cost_per_unit = 800.0
    db.commit()
    snapshot = MarketSnapshot(
        hs_code=product.hs_code,
        market_iso2="IN",
        source="localprice_mock",
        observed_prices=[{"competitor": "Acme", "price": 2000.0, "currency": "USD", "source": "x"}],
    )
    thread = build_margin_thread(product, "IN", snapshot)

    assert thread["margin_basis"] == "actual_cost"
    assert thread["cost_per_unit"] == 800.0
    assert thread["factory_offer"] == 1400.0  # still reported, but not the basis
    c = thread["competitors"][0]
    # (2000 − 800) / 2000 = 0.6, computed against cost — NOT (2000 − 1400)/2000.
    assert c["margin_pct"] == round((2000.0 - 800.0) / 2000.0, 4)
    assert any("actual per-unit cost" in limit for limit in thread["limits"])
    assert not any("Gross headroom" in limit for limit in thread["limits"])


def test_margin_falls_back_to_offer_estimate_without_cost(db, factory, product):
    # No cost on file → the estimate basis, explicitly labelled as such.
    assert product.cost_per_unit is None
    snapshot = MarketSnapshot(
        hs_code=product.hs_code,
        market_iso2="IN",
        source="localprice_mock",
        observed_prices=[{"competitor": "Acme", "price": 2000.0, "currency": "USD", "source": "x"}],
    )
    thread = build_margin_thread(product, "IN", snapshot)

    assert thread["margin_basis"] == "offer_estimate"
    assert thread["cost_per_unit"] is None
    c = thread["competitors"][0]
    # Basis is the 1400 offer midpoint: (2000 − 1400) / 2000 = 0.3.
    assert c["margin_pct"] == round((2000.0 - 1400.0) / 2000.0, 4)
    assert any("Gross headroom" in limit for limit in thread["limits"])


def test_create_product_captures_cost_per_unit(client, auth_headers):
    res = client.post(
        "/api/v1/products",
        headers=auth_headers,
        data={
            "name_ar": "تمر",
            "name_en": "Dates",
            "price_min": "1200",
            "price_max": "1600",
            "cost_per_unit": "800.50",
            "classify": "false",
        },
    )
    assert res.status_code == 202, res.text
    product_id = res.json()["product"]["id"]

    body = client.get(f"/api/v1/products/{product_id}", headers=auth_headers).json()
    assert body["cost_per_unit"] == 800.5


def test_create_product_cost_per_unit_is_optional(client, auth_headers):
    res = client.post(
        "/api/v1/products",
        headers=auth_headers,
        data={"name_ar": "عسل", "name_en": "Honey", "classify": "false"},
    )
    assert res.status_code == 202, res.text
    product_id = res.json()["product"]["id"]

    body = client.get(f"/api/v1/products/{product_id}", headers=auth_headers).json()
    assert body["cost_per_unit"] is None

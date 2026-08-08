"""Optional price coercion on POST /products.

Browsers submit empty ``<input>`` fields as ``""`` (not omitted), so the endpoint
takes the prices as strings and coerces them: blank → unset, numeric → float,
garbage → a clean 400. See A1 in TASKS.md.
"""

from __future__ import annotations


def test_blank_prices_are_accepted_as_unset(client, auth_headers):
    # The browser sends "" for an empty price input; that must not 422.
    res = client.post(
        "/api/v1/products",
        headers=auth_headers,
        data={
            "name_ar": "عسل السدر",
            "name_en": "Sidr Honey",
            "price_min": "",
            "price_max": "",
            "classify": "false",
        },
    )
    assert res.status_code == 202, res.text
    product_id = res.json()["product"]["id"]

    body = client.get(f"/api/v1/products/{product_id}", headers=auth_headers).json()
    assert body["price_min"] is None
    assert body["price_max"] is None


def test_numeric_prices_are_parsed(client, auth_headers):
    res = client.post(
        "/api/v1/products",
        headers=auth_headers,
        data={
            "name_ar": "تمر",
            "name_en": "Dates",
            "price_min": "1200.5",
            "price_max": "1600",
            "classify": "false",
        },
    )
    assert res.status_code == 202, res.text
    product_id = res.json()["product"]["id"]

    body = client.get(f"/api/v1/products/{product_id}", headers=auth_headers).json()
    assert body["price_min"] == 1200.5
    assert body["price_max"] == 1600.0


def test_garbage_price_is_a_clean_400(client, auth_headers):
    res = client.post(
        "/api/v1/products",
        headers=auth_headers,
        data={
            "name_ar": "تمر",
            "name_en": "Dates",
            "price_min": "not-a-number",
            "classify": "false",
        },
    )
    assert res.status_code == 400, res.text
    assert "price_min" in res.json()["detail"]


def test_products_list_serializes_unscored_hs_candidate(client, db, auth_headers):
    """Regression: the deterministic classifier stores ``confidence=None`` for an
    honestly-unscored match (I1). HSCandidate.confidence was a required float, so
    ``GET /products`` 500'd on every product the worker had classified. The list
    must serialize a null confidence and stay 200."""
    import uuid as _uuid

    from app.models import Product

    res = client.post(
        "/api/v1/products",
        headers=auth_headers,
        data={"name_ar": "حليب", "name_en": "milk", "classify": "false"},
    )
    assert res.status_code == 202, res.text
    pid = res.json()["product"]["id"]

    # Mirror exactly what hs_classifier.classify_product writes for an unscored hit.
    product = db.get(Product, _uuid.UUID(pid))
    product.hs_candidates = [
        {
            "code": "040110",
            "confidence": None,
            "rationale": "",
            "in_catalogue": True,
            "provider": "silk_hs_classifier (deterministic)",
            "used_llm": False,
        }
    ]
    product.classification_status = "classified"
    db.commit()

    listing = client.get("/api/v1/products", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    row = next(r for r in listing.json() if r["id"] == pid)
    assert row["hs_candidates"][0]["confidence"] is None

"""Buyer discovery honours the I2 human-confirm gate at the API edge.

Discovery fetches buyer PII, so it must run only on a *human-confirmed* HS code —
never on the code the classifier pre-fills with its top candidate before the user
confirms. The gate mirrors the world-analysis run (both are I2-gated the same way).
"""

from __future__ import annotations

from app.models import Product


def test_discover_blocked_until_hs_confirmed(client, db, factory, auth_headers):
    # A post-classification, pre-confirmation product: hs_code is pre-filled with
    # the top candidate, but the human has not confirmed it (hs_confirmed_by_user
    # is False). Checking hs_code alone would wrongly let discovery through.
    proposed = Product(
        factory_id=factory.id,
        name_ar="مقترح",
        name_en="Proposed Widget",
        currency="USD",
        hs_code="392010",
        hs_confirmed_by_user=False,
    )
    db.add(proposed)
    db.commit()

    resp = client.post(
        f"/api/v1/products/{proposed.id}/discover",
        json={"markets": ["IN"]},
        headers=auth_headers,
    )
    assert resp.status_code == 409  # I2 — no discovery on an unconfirmed HS code


def test_discover_allowed_once_confirmed(client, product, auth_headers, monkeypatch):
    # The `product` fixture is HS-confirmed. Stub the task enqueue so the test
    # isolates the endpoint's gate from the background discovery pipeline/broker.
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.api.buyers.run_discovery.delay",
        lambda product_id, market: calls.append((product_id, market)),
    )

    resp = client.post(
        f"/api/v1/products/{product.id}/discover",
        json={"markets": ["IN", "DE"]},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["markets"] == ["IN", "DE"]
    assert [market for _, market in calls] == ["IN", "DE"]  # one job per market

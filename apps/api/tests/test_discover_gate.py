"""Buyer discovery honours the I2 human-confirm gate on every code path.

Discovery fetches buyer PII, so it must run only on a *human-confirmed* HS code —
never on the code the classifier pre-fills with its top candidate before the user
confirms. The gate mirrors the world-analysis run (both are I2-gated the same way).

Defense-in-depth: the gate is enforced at three layers — the API route, the
``discover_buyers`` service, and the ``run_discovery`` worker task — so no code
path (a direct service call, or a job enqueued past the API) can bypass it.
"""

from __future__ import annotations

import pytest

from app.services.buyer_discovery import HsNotConfirmedError, buyers_for_product, discover_buyers


def test_discover_blocked_until_hs_confirmed(client, db, product, auth_headers):
    # Reproduce the classifier's post-classification, pre-confirmation state on a
    # product whose hs_code already satisfies the hs_codes FK: the code stays set
    # (pre-filled from the top candidate) while the confirmation flag is off.
    # Checking hs_code alone would wrongly let discovery through.
    product.hs_confirmed_by_user = False
    db.commit()

    resp = client.post(
        f"/api/v1/products/{product.id}/discover",
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


def test_service_layer_blocks_unconfirmed_hs(db, product):
    # Layer 2: a *direct* service call must refuse an unconfirmed HS code, even
    # though the API route never reached — this is the real backstop.
    product.hs_confirmed_by_user = False
    db.commit()

    with pytest.raises(HsNotConfirmedError):
        discover_buyers(db, product, "IN")


def test_worker_layer_blocks_unconfirmed_hs(db, product):
    # Layer 3: a job enqueued directly (bypassing the API gate) degrades to an
    # error and creates no buyers, rather than running discovery or crashing.
    from app.workers.tasks import run_discovery

    product.hs_confirmed_by_user = False
    db.commit()

    result = run_discovery(str(product.id), "IN")
    assert result == {"error": "hs code not confirmed"}
    # Nothing was discovered for this product/market.
    assert buyers_for_product(db, product.id, "IN") == []

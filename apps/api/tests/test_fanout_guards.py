"""Fan-out guards on the paid endpoints (audit findings C17/C14, C18, C19).

Three endpoints kick off *paid* provider work from a user-supplied markets list
(or on every call). Without a per-user rate limit, a market cap, and — for the
observed-price layer — a daily paid-call reservation, a simple loop drains the
paid key even with ``SILK_PAID_DAILY_CAP`` set. These tests pin each guard:

* ``POST /products/{id}/deepen/prices`` (C17+C14) — rate-limited, caps the markets
  list, and makes NO provider call once the paid reservation is refused;
* ``POST /products/{id}/discover`` (C18) — rate-limited and caps the markets list;
* ``POST /products`` + ``POST /products/{id}/classify`` (C19) — the paid vision
  intake is rate-limited (both endpoints share one per-user bucket).

The guards are isolated from the downstream pipeline by stubbing the enqueue /
fetch calls, so each test exercises the guard itself, not the paid work.
"""

from __future__ import annotations

from types import SimpleNamespace

import silk_usage

from app.api.buyers import DISCOVER_RATE_LIMIT, MAX_DISCOVER_MARKETS
from app.api.pricing import DEEPEN_PRICES_RATE_LIMIT, MAX_DEEPEN_MARKETS
from app.api.products import PRODUCT_INTAKE_RATE_LIMIT
from app.models import Analysis
from app.services import observed_prices

_OVER_CAP_MARKETS = ["IN", "DE", "US", "FR", "IT", "ES", "NL"]  # >5 distinct


# -- deepen prices (C17 + C14) ---------------------------------------------


def test_deepen_prices_rate_limits_past_limit(client, auth_headers, product, monkeypatch):
    # Isolate the rate-limit guard from the paid fetch itself.
    monkeypatch.setattr(
        observed_prices,
        "fetch_prices_for_market",
        lambda db, prod, market: {"market": market, "skipped": False, "count": 0},
    )
    url = f"/api/v1/products/{product.id}/deepen/prices"
    for _ in range(DEEPEN_PRICES_RATE_LIMIT):
        res = client.post(url, headers=auth_headers, json={"markets": ["IN"]})
        assert res.status_code == 200, res.text
    # One past the window cap is refused.
    res = client.post(url, headers=auth_headers, json={"markets": ["IN"]})
    assert res.status_code == 429


def test_deepen_prices_rejects_over_cap_markets(client, auth_headers, product):
    assert len(_OVER_CAP_MARKETS) > MAX_DEEPEN_MARKETS
    res = client.post(
        f"/api/v1/products/{product.id}/deepen/prices",
        headers=auth_headers,
        json={"markets": _OVER_CAP_MARKETS},
    )
    assert res.status_code == 400, res.text
    assert "max" in res.json()["detail"].lower()


def test_deepen_prices_no_fetch_when_reservation_refused(
    client, auth_headers, product, monkeypatch
):
    # Over the daily paid-call cap: the endpoint must 429 BEFORE any provider call.
    monkeypatch.setattr(silk_usage, "try_reserve_paid_calls", lambda *a, **k: False)
    calls: list = []
    monkeypatch.setattr(
        observed_prices,
        "fetch_prices_for_market",
        lambda db, prod, market: calls.append(market),
    )
    res = client.post(
        f"/api/v1/products/{product.id}/deepen/prices",
        headers=auth_headers,
        json={"markets": ["IN"]},
    )
    assert res.status_code == 429, res.text
    assert calls == []  # the paid price layer was never called


# -- buyer discovery (C18) --------------------------------------------------


def _seed_analysis(db, product) -> Analysis:
    analysis = Analysis(product_id=product.id, product_name=product.name_en, status="classified")
    db.add(analysis)
    db.commit()
    return analysis


def test_discover_rate_limits_past_limit(client, auth_headers, db, product, monkeypatch):
    _seed_analysis(db, product)
    monkeypatch.setattr("app.api.buyers.run_discovery.delay", lambda *a, **k: None)
    url = f"/api/v1/products/{product.id}/discover"
    for _ in range(DISCOVER_RATE_LIMIT):
        res = client.post(url, headers=auth_headers, json={"markets": ["IN"]})
        assert res.status_code == 202, res.text
    res = client.post(url, headers=auth_headers, json={"markets": ["IN"]})
    assert res.status_code == 429


def test_discover_rejects_over_cap_markets(client, auth_headers, product):
    assert len(_OVER_CAP_MARKETS) > MAX_DISCOVER_MARKETS
    res = client.post(
        f"/api/v1/products/{product.id}/discover",
        headers=auth_headers,
        json={"markets": _OVER_CAP_MARKETS},
    )
    assert res.status_code == 400, res.text
    assert "max" in res.json()["detail"].lower()


# -- product intake / re-classify (C19) -------------------------------------


def test_product_create_and_classify_rate_limited(client, auth_headers, product, monkeypatch):
    # Stub the paid intake enqueue so only the guard is under test. The endpoint
    # returns ProductAccepted(task_id=task.id, ...), so the stub needs a .id.
    monkeypatch.setattr(
        "app.api.products.process_product_intake.delay",
        lambda *a, **k: SimpleNamespace(id="stub-task"),
    )
    data = {"name_ar": "منتج", "name_en": "Widget", "classify": "false"}
    for _ in range(PRODUCT_INTAKE_RATE_LIMIT):
        res = client.post("/api/v1/products", headers=auth_headers, data=data)
        assert res.status_code == 202, res.text
    # The next create is refused …
    res = client.post("/api/v1/products", headers=auth_headers, data=data)
    assert res.status_code == 429
    # … and the manual re-classify path shares the same per-user bucket.
    res = client.post(f"/api/v1/products/{product.id}/classify", headers=auth_headers)
    assert res.status_code == 429

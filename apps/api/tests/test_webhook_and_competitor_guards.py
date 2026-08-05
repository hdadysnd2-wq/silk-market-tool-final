"""C5 — fail-closed Smartlead webhook + metered/throttled competitor snapshots.

Two audit MEDIUMs:
  * ``/webhooks/smartlead`` must reject an unsigned request whenever a real
    (non-mock) sending provider is configured — the endpoint is unauthenticated
    and mutates the GLOBAL suppression ledger, so it must fail closed off the
    local mock demo.
  * ``GET /markets/{iso2}/competitors`` can trigger live Comtrade. It must run
    inside a ``budget_scope`` (so those calls charge the ≤150/analysis ceiling)
    AND be per-user rate limited (so a user can't enumerate (hs, iso2) pairs to
    drain the key across requests).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import silk_data_layer

import app.api.markets as markets
import app.api.webhooks as webhooks
import app.services.competitor_snapshot as competitor_snapshot
from app.providers.shipments.comtrade import ComtradeProvider
from app.services import api_budget
from app.services.api_budget import budget_scope

# --- webhook fail-closed ---------------------------------------------------


def test_webhook_rejects_unsigned_when_real_provider_configured(client, monkeypatch):
    """The Verify: unsigned webhook → 401 when a real provider is configured."""
    monkeypatch.setattr(
        webhooks,
        "get_settings",
        lambda: SimpleNamespace(
            smartlead_webhook_secret="",  # no secret set…
            smartlead_api_key="real-smartlead-key",  # …but a REAL ESP is configured
            environment="production",
        ),
    )
    resp = client.post(
        "/api/v1/webhooks/smartlead",
        content=json.dumps({"event": "complained", "message_id": "x"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_webhook_rejects_unsigned_real_provider_even_on_local(client, monkeypatch):
    """A real provider key rejects the unsigned webhook even in local — the open
    path is only for the mock (no ESP key)."""
    monkeypatch.setattr(
        webhooks,
        "get_settings",
        lambda: SimpleNamespace(
            smartlead_webhook_secret="",
            smartlead_api_key="real-smartlead-key",
            environment="local",
        ),
    )
    resp = client.post(
        "/api/v1/webhooks/smartlead",
        content=json.dumps({"event": "complained", "message_id": "x"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_webhook_accepts_valid_signature(client, monkeypatch):
    """With a secret set, a correctly signed request is authenticated (200)."""
    monkeypatch.setattr(
        webhooks, "get_settings", lambda: SimpleNamespace(smartlead_webhook_secret="s3cr3t")
    )
    body = json.dumps({"event": "opened", "message_id": "mock-x"}).encode()
    sig = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    resp = client.post(
        "/api/v1/webhooks/smartlead",
        content=body,
        headers={"Content-Type": "application/json", "X-Smartlead-Signature": sig},
    )
    assert resp.status_code == 200


# --- competitor snapshot: metered + rate limited ---------------------------


def test_competitor_snapshot_charges_budget_when_live(db, monkeypatch, tmp_path):
    """The Verify: a live competitor snapshot charges the active budget.

    The provider is forced live and its data layer stubbed (no network); each
    yearly fetch still charges before the (stubbed) call, so within a scope the
    budget is spent — proving the calls are metered, not the old unmetered bypass.
    A tmp cache_dir keeps the live fetch's write off the committed fixtures.
    """
    monkeypatch.setattr(
        competitor_snapshot,
        "get_comtrade_provider",
        lambda: ComtradeProvider(offline=False, cache_dir=tmp_path),
    )
    monkeypatch.setattr(silk_data_layer, "comtrade_trade", lambda *a, **k: [])

    with budget_scope(limit=150) as budget:
        competitor_snapshot.build_snapshot(db, "392010", "IN")

    assert budget.spent > 0


def test_competitor_endpoint_runs_inside_a_budget_scope(client, monkeypatch, auth_headers):
    """The endpoint wraps the competitor call in a budget scope, so live Comtrade
    charges are metered (charge() sees a non-None budget)."""
    seen: dict[str, object] = {}

    def spy_build(db, hs_code, market_iso2, refresh=False):
        seen["budget"] = api_budget.current_budget()
        return SimpleNamespace(
            hs_code=hs_code,
            market_iso2=market_iso2,
            total_import_usd=None,
            trend_pct=None,
            top_exporters=[],
            yearly_values=[],
            observed_prices=None,
            source="comtrade",
        )

    monkeypatch.setattr(markets, "build_snapshot", spy_build)
    resp = client.get("/api/v1/markets/IN/competitors?hs_code=392010", headers=auth_headers)
    assert resp.status_code == 200
    assert seen["budget"] is not None  # metered: the call ran inside a budget scope


def test_competitor_endpoint_is_per_user_rate_limited(client, auth_headers):
    """A per-user sliding window caps interactive competitor lookups (429 past it)."""
    url = "/api/v1/markets/IN/competitors?hs_code=392010"
    for _ in range(30):
        assert client.get(url, headers=auth_headers).status_code == 200
    assert client.get(url, headers=auth_headers).status_code == 429

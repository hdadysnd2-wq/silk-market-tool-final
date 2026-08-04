"""Per-analysis live-call budget caps Comtrade usage (locked decision #5).

The master prompt requires ≤150 live Comtrade calls per analysis and per-analysis
spend logging. These pin the mechanism and prove the live Comtrade path stops
charging (and degrades) once the budget is exhausted — verifiable offline by
stubbing the engine's data layer.
"""

from __future__ import annotations

import silk_data_layer

from app.providers.shipments.comtrade import ComtradeProvider
from app.services import api_budget


def test_charge_is_unmetered_without_a_scope():
    assert api_budget.current_budget() is None
    assert api_budget.charge(999, source="comtrade") is True  # no ceiling outside a scope


def test_budget_scope_tracks_spend_and_caps():
    with api_budget.budget_scope(limit=3) as budget:
        assert api_budget.charge(2, source="comtrade") is True
        assert budget.spent == 2
        assert budget.remaining == 1
        assert api_budget.charge(1, source="comtrade") is True  # exactly at the limit
        assert budget.remaining == 0
        assert api_budget.charge(1, source="comtrade") is False  # would exceed
        assert budget.spent == 3  # nothing charged on refusal
    # Scope reset on exit — back to unmetered.
    assert api_budget.current_budget() is None


def test_live_comtrade_stops_at_the_budget(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_comtrade_trade(hs_code, reporter, year, flow="M", partner="all"):
        calls["n"] += 1
        return [{"refYear": year, "partnerCode": "699", "primaryValue": 1000.0}]

    monkeypatch.setattr(silk_data_layer, "comtrade_trade", fake_comtrade_trade)
    # Cache to a throwaway dir — the live path writes fetched payloads back to its
    # cache_dir, which must never be the committed fixtures directory.
    provider = ComtradeProvider(offline=False, cache_dir=tmp_path)

    # trade_flows would make one live call per year (3), but the budget allows 2.
    with api_budget.budget_scope(limit=2) as budget:
        provider.trade_flows("392010", "IN", years=3)
        assert calls["n"] == 2  # third year refused by the budget
        assert budget.spent_by_source == {"comtrade": 2}

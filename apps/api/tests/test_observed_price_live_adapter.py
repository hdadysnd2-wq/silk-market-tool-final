"""LIVE observed-price adapter — offline behaviour, registry switch, and I5/I1.

The real ``LocalPriceProvider`` routes observed competitor prices through the
engine's PAID ``LocalPriceAgent``. These tests are hermetic: the engine agent's
``run`` is monkeypatched to a stub, so no network and no vendor key are needed.

They prove:

* mapping — an engine ``DataPoint`` priced listing becomes one
  ``ProviderRecord[ObservedPrice]`` tagged ``ENRICHMENT``, and a ``None`` finding
  (the no-key / no-results / failure case) is dropped, never a fabricated price (I1);
* degradation — a report with only a ``None`` finding, or an agent that raises,
  both yield ``[]`` (declared gap, no exception, I1);
* the registry switch — no key selects the mock, a key selects the live adapter,
  with the mock kept as the offline-green default;
* the deepen gate (I5) — the service refuses outside deepen and never invokes the
  live adapter, even when it is the selected provider.
"""

from __future__ import annotations

from silk_agents import AgentReport
from silk_data_layer import DataPoint
from silk_localprice_agent import LocalPriceAgent

from app.config import Settings
from app.providers.base import ObservedPrice, ProviderRecord, SourceType
from app.providers.pricing.localprice import LocalPriceProvider
from app.providers.pricing.mock import MockPriceProvider
from app.providers.registry import get_price_provider
from app.services import engine, observed_prices


def _stub_report(findings: list[DataPoint]) -> AgentReport:
    return AgentReport("LocalPriceAgent", findings, False, "stub")


def test_maps_priced_listing_and_drops_none_finding(monkeypatch):
    # One real priced listing + one declared-gap finding (the engine's None case).
    captured: dict = {}

    def _run(self, task, instruction=""):
        captured.update(task)
        return _stub_report(
            [
                DataPoint(
                    {
                        "title": "Acme",
                        "price": 12.5,
                        "currency": "USD",
                        "store": "X Mart",
                        "link": "https://x",
                    },
                    "Local retail",
                    0.6,
                ),
                DataPoint(None, "Local retail", 0.0, "no priced listings"),
            ]
        )

    monkeypatch.setattr(LocalPriceAgent, "run", _run)

    records = LocalPriceProvider().observed_prices("040690", "AE", product_name="Medjool Dates")

    # The None finding is dropped — only the observed listing maps through (I1).
    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, ProviderRecord)
    assert isinstance(rec.data, ObservedPrice)
    assert rec.data.competitor == "Acme"
    assert rec.data.price == 12.5
    assert rec.data.currency == "USD"
    assert rec.data.url == "https://x"
    assert rec.data.store == "X Mart"
    assert rec.source is SourceType.ENRICHMENT
    assert rec.provider_name == "localprice_serper"
    assert rec.confidence == 0.6
    # The engine is searched by the PRODUCT NAME (a shopping query), not the HS6.
    assert captured["query"] == "Medjool Dates"
    assert captured["market"] == "AE"


def test_query_falls_back_to_hs_code_without_a_name(monkeypatch):
    captured: dict = {}

    def _run(self, task, instruction=""):
        captured.update(task)
        return _stub_report([DataPoint(None, "Local retail", 0.0, "no query")])

    monkeypatch.setattr(LocalPriceAgent, "run", _run)
    LocalPriceProvider().observed_prices("040690", "AE")
    assert captured["query"] == "040690"  # last-resort fallback


def test_no_key_none_finding_is_declared_gap(monkeypatch):
    # The no-key case: the engine returns a single DataPoint(None, …). The adapter
    # must return [] (a declared gap), never a fabricated price (I1).
    monkeypatch.setattr(
        LocalPriceAgent,
        "run",
        lambda self, task, instruction="": _stub_report(
            [DataPoint(None, "Local retail", 0.0, "requires LOCALPRICE_API_KEY")]
        ),
    )
    assert LocalPriceProvider().observed_prices("040690", "AE") == []


def test_agent_exception_degrades_to_empty(monkeypatch):
    # A vendor/engine hiccup must never crash the deepen run: broad degradation → [].
    def _boom(self, task, instruction=""):
        raise RuntimeError("vendor down")

    monkeypatch.setattr(LocalPriceAgent, "run", _boom)
    assert LocalPriceProvider().observed_prices("040690", "AE") == []


def test_records_are_capped_at_limit(monkeypatch):
    # limit is honoured so a chatty vendor cannot flood the snapshot.
    listing = DataPoint(
        {"title": "S", "price": 3.0, "currency": "USD", "store": "M", "link": "https://s"},
        "Local retail",
        0.6,
    )
    monkeypatch.setattr(
        LocalPriceAgent,
        "run",
        lambda self, task, instruction="": _stub_report([listing] * 5),
    )
    assert len(LocalPriceProvider().observed_prices("040690", "AE", limit=2)) == 2


def test_registry_switches_on_localprice_key():
    # Offline default (no key) → deterministic mock keeps CI green.
    assert isinstance(get_price_provider(Settings(localprice_api_key="")), MockPriceProvider)
    # Key present → the LIVE adapter is selected. This is the SAME key the engine
    # agent reads (LOCALPRICE_API_KEY), so the live path can actually fetch.
    assert isinstance(
        get_price_provider(Settings(localprice_api_key="test-localprice-key")), LocalPriceProvider
    )


def test_live_adapter_never_runs_outside_deepen(db, factory, product, monkeypatch):
    # I5 — with the LIVE adapter selected, the service still refuses outside deepen
    # and never invokes the paid live layer (spy proves zero calls).
    assert engine.deepen_active() is False

    calls: list[tuple[str, str]] = []

    def _spy(self, hs_code, market_iso2, limit=10, product_name=None):
        calls.append((hs_code, market_iso2))
        return []

    monkeypatch.setattr(LocalPriceProvider, "observed_prices", _spy)
    # Wire the service to the live adapter exactly as the registry would with a key.
    monkeypatch.setattr(
        observed_prices,
        "get_price_provider",
        lambda *a, **k: get_price_provider(Settings(localprice_api_key="test-localprice-key")),
    )

    result = observed_prices.fetch_prices_for_market(db, product, "IN")

    assert result["skipped"] is True
    assert result["reason"] == observed_prices.SKIPPED_OUTSIDE_DEEPEN
    assert result["count"] == 0
    assert calls == [], "the paid live adapter must not run outside deepen (I5)"

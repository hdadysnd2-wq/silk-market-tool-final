"""LIVE World Bank / WITS market-enrichment adapter — hermetic (no network).

Locks the Stage-2 live adapter's contract by monkeypatching the engine functions it
routes through (``silk_tariffs_agent.TariffsAgent.run`` for the applied tariff,
``silk_data_layer.world_bank`` for PPP), so no HTTP is ever attempted:

* the tariff **percent** the engine yields is normalised to a **fraction**
  (``5.0%`` → ``0.05``) to match ``MarketEnrichment.applied_tariff_pct``, PPP passes
  through, and the record is tagged ``SourceType.ENRICHMENT``;
* when **both** engine calls fail — whether by returning a ``DataPoint(None, …)``
  (declared gap) or by raising — ``enrich_market`` returns ``None`` (I1), never a
  fabricated number and never an exception;
* the registry stays on the deterministic mock by default and only selects the live
  adapter when ``market_enrichment_live`` is set.
"""

from __future__ import annotations

import silk_data_layer
import silk_tariffs_agent
from silk_agents import AgentReport
from silk_data_layer import DataPoint

from app.config import Settings
from app.providers.base import ProviderRecord, SourceType
from app.providers.market_enrichment.mock import MockMarketEnrichmentProvider
from app.providers.market_enrichment.worldbank_wits import WorldBankWitsEnrichmentProvider
from app.providers.registry import get_market_enrichment_provider


def _stub_tariff(monkeypatch, *, value):
    """Make ``TariffsAgent().run(...)`` return a report whose findings[0] is ``value``."""
    report = AgentReport(
        "TariffsAgent",
        [DataPoint(value, "World Bank WITS", 0.8, "")],
        value is None,
        "stub",
    )
    monkeypatch.setattr(
        silk_tariffs_agent.TariffsAgent, "run", lambda self, task, instruction="": report
    )


def _stub_ppp(monkeypatch, *, value):
    """Make ``silk_data_layer.world_bank(...)`` return a DataPoint carrying ``value``."""
    monkeypatch.setattr(
        silk_data_layer,
        "world_bank",
        lambda iso3, indicator, year=None: DataPoint(value, "World Bank", 0.9, ""),
    )


def test_enrich_market_normalizes_tariff_to_fraction_and_passes_ppp(monkeypatch):
    # Engine yields the tariff as a percent (5.0%) and PPP as a raw figure.
    _stub_tariff(monkeypatch, value=5.0)
    _stub_ppp(monkeypatch, value=42_000.0)

    record = WorldBankWitsEnrichmentProvider().enrich_market("BRA", "392010")

    assert isinstance(record, ProviderRecord)
    assert record.source is SourceType.ENRICHMENT
    assert record.provider_name == "market_enrichment_worldbank_wits"
    # 5.0% → 0.05 fraction (matches MarketEnrichment.applied_tariff_pct).
    assert record.data.applied_tariff_pct == 0.05
    assert record.data.ppp_gni_per_capita == 42_000.0
    # Confidence derives from the present DataPoints (max of tariff 0.8, ppp 0.9).
    assert record.confidence == 0.9


def test_enrich_market_partial_signal_still_returns_record(monkeypatch):
    # PPP present, tariff a declared gap → a record carrying the gap, not None.
    _stub_tariff(monkeypatch, value=None)
    _stub_ppp(monkeypatch, value=30_000.0)

    record = WorldBankWitsEnrichmentProvider().enrich_market("KEN", "392010")

    assert isinstance(record, ProviderRecord)
    assert record.data.applied_tariff_pct is None  # gap, never fabricated (I1)
    assert record.data.ppp_gni_per_capita == 30_000.0
    assert record.confidence == 0.9  # the one present signal's confidence


def test_enrich_market_full_gap_returns_none_on_datapoint_none(monkeypatch):
    # Both engine calls succeed structurally but carry no value → full declared gap.
    _stub_tariff(monkeypatch, value=None)
    _stub_ppp(monkeypatch, value=None)

    assert WorldBankWitsEnrichmentProvider().enrich_market("EGY", "392010") is None


def test_enrich_market_full_gap_returns_none_when_engine_raises(monkeypatch):
    # Both engine calls blow up (network / volatile WITS) → None, never an exception,
    # never a fabricated number (I1).
    def _boom(*args, **kwargs):
        raise RuntimeError("live engine unavailable")

    monkeypatch.setattr(silk_tariffs_agent.TariffsAgent, "run", _boom)
    monkeypatch.setattr(silk_data_layer, "world_bank", _boom)

    assert WorldBankWitsEnrichmentProvider().enrich_market("DEU", "392010") is None


def test_registry_defaults_to_mock():
    settings = Settings(market_enrichment_live=False)
    provider = get_market_enrichment_provider(settings)
    assert isinstance(provider, MockMarketEnrichmentProvider)
    assert provider.name == "market_enrichment_mock"


def test_registry_selects_live_adapter_when_flagged():
    settings = Settings(market_enrichment_live=True)
    provider = get_market_enrichment_provider(settings)
    assert isinstance(provider, WorldBankWitsEnrichmentProvider)
    assert provider.name == "market_enrichment_worldbank_wits"

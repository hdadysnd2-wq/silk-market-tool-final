"""Regression locks: engine importer-intel agents behind the registry (W3 item 4).

Volza/Explee are ADDITIONAL buyer sources, fail-closed twice over: the registry
registers them only when their paid key is configured, and the wrapped engine
agents (PAID=True) structurally refuse to execute outside the deepen scope even
with a key — so the free path and the keyless suite see zero behavior change.
The platform's customs + maps discovery stays primary.
"""

from __future__ import annotations

from app.config import Settings
from app.models import Buyer, BuyerSource
from app.providers.base import SOURCE_QUALITY, SourceType
from app.providers.buyers_intel.engine_importers import (
    ExpleeImporterProvider,
    VolzaImporterProvider,
)
from app.providers.registry import get_importer_intel_providers
from app.services import engine
from app.services.buyer_discovery import discover_buyers


def test_registry_is_empty_without_keys():
    assert get_importer_intel_providers(Settings(environment="local")) == []


def test_registry_registers_per_key():
    settings = Settings(environment="local", volza_api_key="k1")
    names = [p.name for p in get_importer_intel_providers(settings)]
    assert names == ["volza"]

    settings = Settings(environment="local", volza_api_key="k1", explee_api_key="k2")
    names = [p.name for p in get_importer_intel_providers(settings)]
    assert names == ["volza", "explee"]


def test_agents_refuse_outside_deepen_even_with_keys(monkeypatch):
    # Engine invariant A4: PAID agents cannot execute outside deepen_context —
    # the provider yields [] with no vendor call, even with keys in the env.
    monkeypatch.setenv("VOLZA_API_KEY", "k1")
    monkeypatch.setenv("EXPLEE_API_KEY", "k2")

    def _no_network(*a, **k):
        raise AssertionError("no vendor call may happen outside deepen")

    monkeypatch.setattr("silk_volza_agent.importers_by_name", _no_network)
    monkeypatch.setattr("silk_explee_agent.discover_buyers", _no_network)

    assert VolzaImporterProvider().named_importers("392010", "IN") == []
    assert ExpleeImporterProvider().named_importers("392010", "IN", "film") == []


def test_deepen_scoped_discovery_upserts_importer_intel_buyers(
    db, factory, product, market, monkeypatch
):
    from silk_data_layer import DataPoint, _today

    monkeypatch.setenv("VOLZA_API_KEY", "k1")
    settings = Settings(environment="local", volza_api_key="k1")
    monkeypatch.setattr(
        "app.providers.registry.get_importer_intel_providers.__defaults__", (settings,)
    )
    monkeypatch.setattr(
        "app.services.buyer_discovery.get_importer_intel_providers",
        lambda settings=None: get_importer_intel_providers(settings),
        raising=False,
    )
    monkeypatch.setattr("app.providers.registry.get_settings", lambda: settings, raising=True)
    monkeypatch.setattr(
        "silk_volza_agent.importers_by_name",
        lambda hs, market_, partner="SAU": [
            DataPoint("Bharat Films Pvt Ltd", "Volza", 0.85, "bill of lading", _today())
        ],
    )

    with engine.deepen_scope(True):
        discover_buyers(db, product, "IN")

    intel_buyers = db.query(Buyer).filter(Buyer.source == BuyerSource.importer_intel).all()
    assert [b.name for b in intel_buyers] == ["Bharat Films Pvt Ltd"]
    assert intel_buyers[0].legal_review_required is True
    assert float(intel_buyers[0].source_confidence) == 0.85


def test_source_quality_covers_importer_intel():
    assert SourceType.IMPORTER_INTEL in SOURCE_QUALITY
    # Observed trade activity by name: above enrichment, below raw customs.
    assert SOURCE_QUALITY[SourceType.ENRICHMENT] < SOURCE_QUALITY[SourceType.IMPORTER_INTEL]
    assert SOURCE_QUALITY[SourceType.IMPORTER_INTEL] < SOURCE_QUALITY[SourceType.CUSTOMS]

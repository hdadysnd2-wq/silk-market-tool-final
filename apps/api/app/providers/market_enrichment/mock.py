"""Deterministic mock for the Stage-2 market-enrichment layer (offline / no key).

Stands in for the live World Bank / WITS calls: given a market and HS6 it returns
a stable applied tariff and a PPP proxy, seeded off (importer, hs6) so the funnel
is reproducible in tests and demos. Live, these are budgeted paid calls through
the engine's data layer; here they are free and deterministic. A real failure
would return ``None`` (a declared gap, I1) — the mock always succeeds.
"""

from __future__ import annotations

from app.providers.base import MarketEnrichment, ProviderRecord, SourceType
from app.providers.determinism import rng_for


class MockMarketEnrichmentProvider:
    """Applied tariff + PPP per (importer, hs6), deterministic."""

    name = "market_enrichment_mock"

    def __init__(self, seed: int = 2027) -> None:
        self._seed = seed

    def enrich_market(
        self, importer_iso3: str, hs6: str
    ) -> ProviderRecord[MarketEnrichment] | None:
        rng = rng_for(importer_iso3.upper(), hs6, salt=self._seed)
        return ProviderRecord(
            data=MarketEnrichment(
                # Applied import tariff for the HS6 (fraction): 0%–20%.
                applied_tariff_pct=round(rng.uniform(0.0, 0.20), 4),
                # PPP GNI per capita proxy for demand quality: $3k–$65k.
                ppp_gni_per_capita=round(rng.uniform(3_000, 65_000), 0),
            ),
            # ENRICHMENT, not COMTRADE: fabricated demo values must never carry
            # a real data source's label (audit 2026-08-07 C3 / I1). The
            # provider_name already says "mock"; the source now agrees.
            source=SourceType.ENRICHMENT,
            provider_name=self.name,
            confidence=0.7,
        )

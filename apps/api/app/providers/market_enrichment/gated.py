"""Fail-closed gate for Stage-2 market enrichment outside ``local`` (C3).

Without ``MARKET_ENRICHMENT_LIVE=1`` a production funnel was silently scoring
markets on the mock's fabricated tariff/PPP values (stamped, until this wave,
as COMTRADE). Enrichment's protocol already defines the honest degradation: a
``None`` record is a declared gap (I1) that the ranker scores without those
components. The gate returns exactly that.
"""

from __future__ import annotations

from app.logging import get_logger
from app.providers.base import MarketEnrichment, ProviderRecord

log = get_logger(__name__)

GATE_REASON = (
    "Market enrichment is gated: MARKET_ENRICHMENT_LIVE is not enabled and this "
    "is not a local environment, so no tariff/PPP value may be fabricated (I1). "
    "Set MARKET_ENRICHMENT_LIVE=1 (World Bank / WITS, keyless) for live values, "
    "or ALLOW_MOCK_DATA=1 for an explicit demo deployment."
)


class GatedMarketEnrichmentProvider:
    """Refuses to fabricate: every market is a declared enrichment gap."""

    name = "gated-market-enrichment"

    def enrich_market(
        self, importer_iso3: str, hs6: str
    ) -> ProviderRecord[MarketEnrichment] | None:
        log.warning(
            "market_enrichment_gated",
            importer=importer_iso3,
            hs6=hs6,
            reason=GATE_REASON,
        )
        return None

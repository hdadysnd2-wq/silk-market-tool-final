"""Fail-closed gate for the company-level shipments slot outside ``local`` (C3).

The 2026-08-07 audit pattern, applied to buyer discovery's customs step: the
registry used to hand out ``MockShipmentsProvider`` UNCONDITIONALLY, so a
keyless production deploy silently minted fabricated importer companies and
persisted them as ``BuyerSource.customs`` rows. Prices and market enrichment
already fail closed in exactly this situation (``GatedPriceProvider`` /
``GatedMarketEnrichmentProvider``); company-level shipments now follow the same
rule: no ``VOLZA_API_KEY`` outside ``local`` (without the explicit
``ALLOW_MOCK_DATA=1`` demo opt-in) yields a **declared gap** — an empty
importer list — never a fabricated buyer presented as observed customs data.
"""

from __future__ import annotations

from app.logging import get_logger
from app.providers.base import ExporterShare, ProviderRecord, ShipmentRecord, TradeFlow

log = get_logger(__name__)

GATE_REASON = (
    "Company-level customs shipments are gated: no VOLZA_API_KEY is configured "
    "and this is not a local environment, so no importer may be fabricated (I1). "
    "Set VOLZA_API_KEY for live bill-of-lading importers, or ALLOW_MOCK_DATA=1 "
    "for an explicit demo deployment (see docs/LAUNCH_KEYS.md)."
)


class GatedShipmentsProvider:
    """Refuses to fabricate: every method is an empty, declared-gap list."""

    name = "gated-shipments"

    def importer_shipments(
        self, hs_code: str, importer_iso2: str, limit: int = 100
    ) -> list[ProviderRecord[ShipmentRecord]]:
        log.warning(
            "importer_shipments_gated",
            hs_code=hs_code,
            market=importer_iso2,
            reason=GATE_REASON,
        )
        return []

    def trade_flows(
        self, hs_code: str, importer_iso2: str, years: int = 3
    ) -> list[ProviderRecord[TradeFlow]]:
        log.warning("trade_flows_gated", hs_code=hs_code, market=importer_iso2, reason=GATE_REASON)
        return []

    def top_exporters(
        self, hs_code: str, importer_iso2: str, limit: int = 10
    ) -> list[ProviderRecord[ExporterShare]]:
        log.warning(
            "top_exporters_gated", hs_code=hs_code, market=importer_iso2, reason=GATE_REASON
        )
        return []

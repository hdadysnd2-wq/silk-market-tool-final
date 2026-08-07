"""Deterministic customs-shipment stand-in — loudly labeled SAMPLE data.

Generates a stable set of importer companies and their shipment history for a
given (HS code, market) so buyer discovery has transaction-level data to work
with even without a paid customs feed. Real bulk data is loaded separately by
``csv_ingest`` into the same ``shipments`` table; the live vendor seam is
``providers/shipments/volza.py`` (J4).

Every fabricated company name carries the ``SAMPLE_NAME_PREFIX`` and the
provider is named ``customs_sample`` so a demo buyer can never read as observed
customs data — the prefix travels through discovery into ``Buyer.name`` and
surfaces verbatim in the buyers UI and the executive report (I1).
"""

from __future__ import annotations

from datetime import date, timedelta

from app.models.base import utcnow
from app.providers.base import (
    ExporterShare,
    ProviderRecord,
    ShipmentRecord,
    SourceType,
    TradeFlow,
)
from app.providers.countries import country_name
from app.providers.determinism import rng_for

#: Believable importer name fragments per market, kept deterministic.
_IMPORTER_STEMS = [
    "Continental",
    "Prime",
    "Delta",
    "Meridian",
    "Apex",
    "Horizon",
    "Unity",
    "Crescent",
    "Summit",
    "Vanguard",
    "Orient",
    "Pioneer",
    "Atlas",
    "Cedar",
    "Nova",
    "Global",
    "Coastal",
    "Pearl",
    "Falcon",
    "Anchor",
]
_IMPORTER_TYPES = {
    "39": ["Plastics", "Polymers", "Packaging", "Trading", "Industries"],
    "04": ["Foods", "Dairy", "Trading", "Distribution", "Provisions"],
    "17": ["Confectionery", "Foods", "Sweets", "Trading", "Provisions"],
    "19": ["Foods", "Bakery", "Trading", "Provisions", "Distribution"],
    "20": ["Foods", "Preserves", "Trading", "Provisions", "Distribution"],
    "08": ["Dates", "Dryfruits", "Foods", "Trading", "Provisions"],
}
_ORIGINS = ["CN", "IN", "TR", "DE", "SA", "AE", "US", "IT", "TH", "MY"]

#: Loud label carried by every fabricated importer name (J4). Constant, so the
#: generated names stay deterministic; the prefix flows through discovery into
#: ``Buyer.name`` and renders verbatim wherever the buyer is shown.
SAMPLE_NAME_PREFIX = "SAMPLE — "


def _type_pool(hs_code: str) -> list[str]:
    return _IMPORTER_TYPES.get(hs_code[:2], ["Trading", "Industries", "Distribution"])


class MockShipmentsProvider:
    name = "customs_sample"

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def _importers(self, hs_code: str, importer_iso2: str, count: int) -> list[str]:
        rng = rng_for(hs_code, importer_iso2, self._seed, salt=1)
        types = _type_pool(hs_code)
        names: list[str] = []
        used: set[str] = set()
        while len(names) < count:
            stem = rng.choice(_IMPORTER_STEMS)
            kind = rng.choice(types)
            name = f"{SAMPLE_NAME_PREFIX}{stem} {kind}"
            if name not in used:
                used.add(name)
                names.append(name)
        return names

    def importer_shipments(
        self, hs_code: str, importer_iso2: str, limit: int = 100
    ) -> list[ProviderRecord[ShipmentRecord]]:
        rng = rng_for(hs_code, importer_iso2, self._seed, salt=2)
        importer_count = rng.randint(6, 10)
        importers = self._importers(hs_code, importer_iso2, importer_count)
        today = date(2026, 6, 30)

        records: list[ProviderRecord[ShipmentRecord]] = []
        for name in importers:
            company_rng = rng_for(name, importer_iso2, hs_code, salt=3)
            shipment_count = company_rng.randint(2, 14)
            for _ in range(shipment_count):
                days_ago = company_rng.randint(5, 420)
                value = round(company_rng.uniform(8_000, 180_000), 2)
                records.append(
                    ProviderRecord(
                        data=ShipmentRecord(
                            consignee_name=name,
                            hs_code=hs_code,
                            origin_iso2=company_rng.choice(_ORIGINS),
                            dest_iso2=importer_iso2,
                            shipment_date=today - timedelta(days=days_ago),
                            value_usd=value,
                            quantity=round(value / company_rng.uniform(1.5, 4.0), 1),
                            quantity_unit="kg",
                            consignee_city=None,
                            external_id=None,
                        ),
                        source=SourceType.CUSTOMS,
                        provider_name=self.name,
                        confidence=0.85,
                        fetched_at=utcnow(),
                    )
                )
                if len(records) >= limit:
                    return records
        return records

    def trade_flows(
        self, hs_code: str, importer_iso2: str, years: int = 3
    ) -> list[ProviderRecord[TradeFlow]]:
        rng = rng_for(hs_code, importer_iso2, self._seed, salt=4)
        base = rng.uniform(4_000_000, 40_000_000)
        records = []
        for offset in range(years, 0, -1):
            year = 2026 - offset
            value = round(base * (1 + 0.06 * (years - offset)), 2)
            records.append(
                ProviderRecord(
                    data=TradeFlow(
                        hs_code=hs_code,
                        importer_iso2=importer_iso2,
                        year=year,
                        value_usd=value,
                    ),
                    source=SourceType.CUSTOMS,
                    provider_name=self.name,
                    confidence=0.6,
                    fetched_at=utcnow(),
                )
            )
        return records

    def top_exporters(
        self, hs_code: str, importer_iso2: str, limit: int = 10
    ) -> list[ProviderRecord[ExporterShare]]:
        rng = rng_for(hs_code, importer_iso2, self._seed, salt=5)
        origins = rng.sample(_ORIGINS, k=min(limit, len(_ORIGINS)))
        weights = sorted((rng.uniform(0.5, 5.0) for _ in origins), reverse=True)
        total = sum(weights)
        records = []
        for iso2, weight in zip(origins, weights, strict=False):
            records.append(
                ProviderRecord(
                    data=ExporterShare(
                        exporter_iso2=iso2,
                        exporter_name=country_name(iso2),
                        value_usd=round(weight * 1_000_000, 2),
                        share_pct=round(100 * weight / total, 2),
                        year=2025,
                    ),
                    source=SourceType.CUSTOMS,
                    provider_name=self.name,
                    confidence=0.6,
                    fetched_at=utcnow(),
                )
            )
        return records

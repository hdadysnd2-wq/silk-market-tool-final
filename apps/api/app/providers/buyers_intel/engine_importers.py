"""Engine importer-intel adapters — Volza / Explee as additional buyer sources.

Wave 3 item 4: the engine's paid importer agents are registered behind the
registry as ADDITIONAL discovery providers; the platform's own customs + maps
discovery stays primary. Both wrap the engine AGENT classes (never the raw
module functions), so the engine's structural PAID guard is inherited intact:
outside ``silk_context.deepen_context()`` the agent returns a skipped report
WITHOUT attempting any call, even with a key configured (engine invariant A4 /
platform I5). Keyless, the agents return declared gaps — company names are
never fabricated (I1). Either way this adapter yields ``[]`` rather than
raising into a discovery run.

The registry additionally registers these only when their key is configured
(fail-closed twice over); the keys are read from the same env vars the engine
agents consume (``VOLZA_API_KEY`` / ``EXPLEE_API_KEY``).
"""

from __future__ import annotations

from app.logging import get_logger
from app.providers.base import ImporterLead, ProviderRecord, SourceType

log = get_logger(__name__)


def _leads_from_report(report, provider_name: str) -> list[ProviderRecord[ImporterLead]]:
    """AgentReport findings → provider records; gaps (value=None) drop out."""
    records: list[ProviderRecord[ImporterLead]] = []
    for finding in report.findings:
        if finding.value is None:
            continue  # declared gap (no key / no data) — never a fabricated name
        records.append(
            ProviderRecord(
                data=ImporterLead(name=str(finding.value), detail=finding.note or None),
                source=SourceType.IMPORTER_INTEL,
                provider_name=provider_name,
                confidence=float(finding.confidence or 0.0),
            )
        )
    return records


class VolzaImporterProvider:
    """Named importers of an HS code into a market, from Volza bills of lading."""

    name = "volza"

    def named_importers(
        self, hs_code: str, market_iso2: str, product_name: str | None = None
    ) -> list[ProviderRecord[ImporterLead]]:
        try:
            from silk_volza_agent import VolzaAgent

            from app.providers.countries import iso2_to_iso3

            iso3 = iso2_to_iso3(market_iso2)
            if not iso3:
                log.warning("volza_no_iso3_mapping", market=market_iso2)
                return []
            report = VolzaAgent().run({"hs_code": hs_code, "market": iso3, "partner": "SAU"})
        except Exception as exc:  # noqa: BLE001 — degrade, never break discovery
            log.warning("volza_importers_failed", market=market_iso2, error=str(exc))
            return []
        return _leads_from_report(report, self.name)


class ExpleeImporterProvider:
    """Buyer/company leads for a product query in a market, from Explee."""

    name = "explee"

    def named_importers(
        self, hs_code: str, market_iso2: str, product_name: str | None = None
    ) -> list[ProviderRecord[ImporterLead]]:
        try:
            from silk_explee_agent import ExpleeAgent

            query = product_name or hs_code
            report = ExpleeAgent().run({"query": query, "market": market_iso2})
        except Exception as exc:  # noqa: BLE001 — degrade, never break discovery
            log.warning("explee_buyers_failed", market=market_iso2, error=str(exc))
            return []
        return _leads_from_report(report, self.name)

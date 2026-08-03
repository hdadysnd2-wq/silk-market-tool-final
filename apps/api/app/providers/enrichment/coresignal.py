"""Coresignal firmographic enrichment adapter.

Activated only when ``CORESIGNAL_API_KEY`` is set; otherwise the mock is used.
The response mapping is intentionally defensive because Coresignal's schema
varies by plan and endpoint.
"""

from __future__ import annotations

import httpx

from app.logging import get_logger
from app.providers.base import CompanyFirmographics, ProviderRecord, SourceType

log = get_logger(__name__)

CORESIGNAL_SEARCH_URL = (
    "https://api.coresignal.com/cdapi/v1/professional_network/company/search/filter"
)
CORESIGNAL_COLLECT_URL = "https://api.coresignal.com/cdapi/v1/professional_network/company/collect"


class CoresignalProvider:
    name = "coresignal"

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def enrich_company(
        self, name: str, country_iso2: str, domain: str | None = None
    ) -> ProviderRecord[CompanyFirmographics] | None:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                search = client.post(
                    CORESIGNAL_SEARCH_URL,
                    headers=self._headers(),
                    json={"name": name} if not domain else {"website": domain},
                )
                search.raise_for_status()
                ids = search.json()
                if not ids:
                    return None
                detail = client.get(f"{CORESIGNAL_COLLECT_URL}/{ids[0]}", headers=self._headers())
                detail.raise_for_status()
                data = detail.json()
        # Coresignal's schema varies by plan, so the search result may not be the
        # assumed non-empty list; degrade on any failure (network, non-JSON body,
        # unexpected shape) to None rather than crashing the discovery run (I1).
        except Exception as exc:
            log.warning("coresignal_failed", company=name, error=str(exc))
            return None

        firmographics = CompanyFirmographics(
            name=data.get("name", name),
            country_iso2=country_iso2,
            domain=data.get("website"),
            website=data.get("website"),
            industry=data.get("industry"),
            employee_count=data.get("employees_count"),
            city=data.get("headquarters_city"),
            revenue_band=data.get("revenue_annual_range"),
            key_people=[],
        )
        return ProviderRecord(
            data=firmographics,
            source=SourceType.ENRICHMENT,
            provider_name=self.name,
            confidence=0.75,
        )

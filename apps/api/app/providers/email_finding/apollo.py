"""Apollo email-finding adapter (primary source in the waterfall)."""

from __future__ import annotations

import httpx

from app.logging import get_logger
from app.providers.base import FoundContact, ProviderRecord, SourceType

log = get_logger(__name__)

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/search"


class ApolloEmailFinderProvider:
    name = "apollo"

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def find_contacts(
        self, company_name: str, domain: str | None, country_iso2: str
    ) -> list[ProviderRecord[FoundContact]]:
        payload = {
            "api_key": self._api_key,
            "q_organization_domains": domain or "",
            "person_titles": ["procurement", "purchasing", "import", "buyer"],
            "page": 1,
            "per_page": 3,
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(APOLLO_SEARCH_URL, json=payload)
                response.raise_for_status()
                people = response.json().get("people", [])
        # Degrade on any failure (network, non-JSON body, unexpected shape) to an
        # empty result rather than crashing the discovery run (I1).
        except Exception as exc:
            log.warning("apollo_failed", company=company_name, error=str(exc))
            return []

        records = []
        for person in people:
            email = person.get("email")
            if not email:
                continue
            records.append(
                ProviderRecord(
                    data=FoundContact(
                        email=email,
                        full_name=person.get("name"),
                        title=person.get("title"),
                        found_via="apollo",
                    ),
                    source=SourceType.ENRICHMENT,
                    provider_name=self.name,
                    confidence=0.7,
                )
            )
        return records

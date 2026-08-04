"""Apollo email-finding adapter (primary source in the waterfall)."""

from __future__ import annotations

import httpx

from app.logging import get_logger
from app.providers.base import FoundContact, ProviderRecord, SourceType

log = get_logger(__name__)

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/search"


def _is_revealed_email(email: str | None, status: str) -> bool:
    """True only for a real, usable address.

    Apollo's ``mixed_people/search`` returns *locked/masked* emails unless they
    are revealed via the People-Enrichment endpoint — the masked value is the
    literal placeholder ``email_not_unlocked@domain.com`` (and ``email_status`` is
    ``locked``/``unavailable``). Storing a masked address would be a dead lead
    that hurts deliverability, so we drop it at the source rather than persist it
    (I1 — a missing contact is a declared gap, not a fabricated address).
    """
    if not email or "@" not in email:
        return False
    lowered = email.lower()
    if "not_unlocked" in lowered or lowered.endswith("@domain.com"):
        return False
    return status not in {"locked", "unavailable"}


class ApolloEmailFinderProvider:
    name = "apollo"

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def find_contacts(
        self, company_name: str, domain: str | None, country_iso2: str
    ) -> list[ProviderRecord[FoundContact]]:
        # Modern Apollo authenticates via the ``X-Api-Key`` header, not a body
        # field; sending the key in the JSON body is rejected/ignored.
        headers = {"X-Api-Key": self._api_key, "Content-Type": "application/json"}
        payload = {
            "q_organization_domains": domain or "",
            "person_titles": ["procurement", "purchasing", "import", "buyer"],
            "page": 1,
            "per_page": 3,
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(APOLLO_SEARCH_URL, json=payload, headers=headers)
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
            status = (person.get("email_status") or "").lower()
            # Skip locked/masked results — they need the reveal endpoint; storing
            # the placeholder address would be a guaranteed bounce.
            if not _is_revealed_email(email, status):
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

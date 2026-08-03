"""Deterministic email-finding stand-in (Apollo-shaped) plus a pattern fallback."""

from __future__ import annotations

from app.providers.base import FoundContact, ProviderRecord, SourceType
from app.providers.determinism import rng_for

_TITLES = ["Procurement Manager", "Import Manager", "Purchasing Lead", "Category Buyer"]
_FIRST = ["Ahmed", "Maria", "Rajesh", "Chen", "Thomas", "Sofia", "Omar", "Priya", "Lukas"]
_LAST = ["Khan", "Silva", "Meyer", "Rossi", "Nakamura", "Fernandez", "Haddad", "Novak"]


class MockEmailFinderProvider:
    name = "mock_apollo"

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def find_contacts(
        self, company_name: str, domain: str | None, country_iso2: str
    ) -> list[ProviderRecord[FoundContact]]:
        rng = rng_for(company_name, country_iso2, self._seed)
        effective_domain = domain or f"{_slug(company_name)}.example.com"

        # A share of companies have no discoverable contact from the primary
        # source; the waterfall then falls back to a pattern guess.
        if rng.random() < 0.25:
            return []

        contacts: list[ProviderRecord[FoundContact]] = []
        for _ in range(rng.randint(1, 2)):
            first = rng.choice(_FIRST)
            last = rng.choice(_LAST)
            email = f"{first.lower()}.{last.lower()}@{effective_domain}"
            contacts.append(
                ProviderRecord(
                    data=FoundContact(
                        email=email,
                        full_name=f"{first} {last}",
                        title=rng.choice(_TITLES),
                        found_via="apollo",
                    ),
                    source=SourceType.ENRICHMENT,
                    provider_name=self.name,
                    confidence=round(rng.uniform(0.6, 0.9), 2),
                )
            )
        return contacts


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())[:24] or "company"

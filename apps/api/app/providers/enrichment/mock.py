"""Deterministic firmographic enrichment stand-in (Coresignal-shaped)."""

from __future__ import annotations

from app.providers.base import (
    CompanyFirmographics,
    ProviderRecord,
    SourceType,
)
from app.providers.countries import country_name
from app.providers.determinism import rng_for

_INDUSTRIES = [
    "Plastics Manufacturing",
    "Wholesale Distribution",
    "Food & Beverage",
    "Packaging",
    "Import & Export",
    "Retail Chains",
    "Industrial Supply",
]
_REVENUE_BANDS = ["$1M–$10M", "$10M–$50M", "$50M–$100M", "$100M+"]
_TITLES = ["Procurement Manager", "Head of Import", "Purchasing Director", "Category Buyer"]
_FIRST = ["Ahmed", "Maria", "Rajesh", "Chen", "Thomas", "Sofia", "Omar", "Priya", "Lukas"]
_LAST = ["Khan", "Silva", "Meyer", "Rossi", "Nakamura", "Fernandez", "Haddad", "Novak"]


class MockEnrichmentProvider:
    name = "mock_coresignal"

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def enrich_company(
        self, name: str, country_iso2: str, domain: str | None = None
    ) -> ProviderRecord[CompanyFirmographics] | None:
        rng = rng_for(name, country_iso2, self._seed)
        # Not every company enriches — mirror real match rates so the pipeline
        # exercises the "enrichment missing" branch.
        if rng.random() < 0.15:
            return None

        slug = _slug(name)
        resolved_domain = domain or f"{slug}.example{_tld(country_iso2)}"
        people = [
            {
                "full_name": f"{rng.choice(_FIRST)} {rng.choice(_LAST)}",
                "title": rng.choice(_TITLES),
            }
            for _ in range(rng.randint(1, 2))
        ]
        firmographics = CompanyFirmographics(
            name=name,
            country_iso2=country_iso2,
            domain=resolved_domain,
            website=f"https://{resolved_domain}",
            industry=rng.choice(_INDUSTRIES),
            employee_count=rng.choice([12, 34, 65, 120, 240, 480, 900]),
            city=country_name(country_iso2),
            revenue_band=rng.choice(_REVENUE_BANDS),
            key_people=people,
        )
        return ProviderRecord(
            data=firmographics,
            source=SourceType.ENRICHMENT,
            provider_name=self.name,
            confidence=round(rng.uniform(0.55, 0.9), 2),
        )


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())[:24] or "company"


def _tld(country_iso2: str) -> str:
    return {"DE": ".de", "IN": ".in", "EG": ".com", "AE": ".ae"}.get(country_iso2.upper(), ".com")

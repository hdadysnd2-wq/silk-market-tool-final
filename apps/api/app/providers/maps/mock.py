"""Deterministic Google-Maps-style long-tail discovery stand-in (Outscraper-shaped).

Maps-derived rows are the weakest intent signal and are flagged for legal review,
so services keep them in their own tier.
"""

from __future__ import annotations

from app.providers.base import MapsPlace, ProviderRecord, SourceType
from app.providers.countries import country_name
from app.providers.determinism import rng_for

_STEMS = [
    "Metro",
    "City",
    "Regional",
    "United",
    "Star",
    "Blue",
    "Green",
    "First",
    "Central",
    "Grand",
    "Royal",
    "Euro",
    "Trade",
    "Market",
]
_KINDS = ["Distributors", "Wholesale", "Trading Co", "Supplies", "Import House"]


class MockMapsProvider:
    name = "mock_outscraper"

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def search_importers(
        self, query: str, country_iso2: str, limit: int = 20
    ) -> list[ProviderRecord[MapsPlace]]:
        rng = rng_for(query, country_iso2, self._seed)
        count = min(limit, rng.randint(4, 9))
        results: list[ProviderRecord[MapsPlace]] = []
        used: set[str] = set()
        while len(results) < count:
            name = f"{rng.choice(_STEMS)} {rng.choice(_KINDS)}"
            if name in used:
                continue
            used.add(name)
            slug = "".join(ch for ch in name.lower() if ch.isalnum())[:20]
            results.append(
                ProviderRecord(
                    data=MapsPlace(
                        name=name,
                        country_iso2=country_iso2,
                        address=f"{rng.randint(1, 300)} Trade St, {country_name(country_iso2)}",
                        phone=f"+{rng.randint(20, 99)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}",
                        website=f"https://{slug}.example.com",
                        rating=round(rng.uniform(3.6, 4.9), 1),
                        city=country_name(country_iso2),
                    ),
                    source=SourceType.MAPS,
                    provider_name=self.name,
                    confidence=round(rng.uniform(0.3, 0.5), 2),
                )
            )
        return results

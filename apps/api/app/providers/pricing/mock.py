"""Deterministic mock for the paid local-price layer (offline / no key).

Stands in for a real observed-price vendor: given an HS code and a market, it
returns a stable set of named competitors with observed listing prices. Values are
seeded off (hs_code, market) so the pipeline is reproducible in tests and demos.
Every price is an *observed* listing with a source link — never an estimate.
"""

from __future__ import annotations

from app.providers.base import ObservedPrice, ProviderRecord, SourceType
from app.providers.determinism import rng_for

_COMPETITORS = [
    "Alahlia Foods",
    "Gulf Pantry",
    "Nile Traders",
    "Levant Select",
    "Desert Harvest",
    "Cedar & Co",
]


class MockPriceProvider:
    """Observed competitor prices, deterministic per (hs_code, market)."""

    name = "localprice_mock"

    def __init__(self, seed: int = 1337) -> None:
        self._seed = seed

    def observed_prices(
        self, hs_code: str, market_iso2: str, limit: int = 10
    ) -> list[ProviderRecord[ObservedPrice]]:
        rng = rng_for(hs_code, market_iso2, salt=self._seed)
        count = min(3 + rng.randint(0, 2), limit, len(_COMPETITORS))
        market = market_iso2.upper()
        out: list[ProviderRecord[ObservedPrice]] = []
        for competitor in _COMPETITORS[:count]:
            slug = competitor.lower().replace(" ", "-").replace("&", "and")
            out.append(
                ProviderRecord(
                    data=ObservedPrice(
                        competitor=competitor,
                        price=round(rng.uniform(8.0, 40.0), 2),
                        currency="USD",
                        url=f"https://listings.example/{market.lower()}/{slug}",
                        store=f"{market} Marketplace",
                    ),
                    source=SourceType.ENRICHMENT,
                    provider_name=self.name,
                    confidence=0.7,
                )
            )
        return out

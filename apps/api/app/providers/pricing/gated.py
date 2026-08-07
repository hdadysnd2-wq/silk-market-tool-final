"""Fail-closed gate for the observed-price slot outside ``local`` (C3).

The 2026-08-07 audit found that a keyless production deploy persisted the mock
provider's fabricated prices — invented competitor names with
``listings.example`` URLs — into ``MarketSnapshot.observed_prices`` and rendered
them in the client-facing executive report. Sending already fails closed in
exactly this situation (``GatedSendingProvider``); observed prices now follow
the same rule: no key outside ``local`` (without the explicit
``ALLOW_MOCK_DATA=1`` demo opt-in) yields a **declared gap** — an empty list —
never fabricated data presented as observed.
"""

from __future__ import annotations

from app.logging import get_logger
from app.providers.base import ObservedPrice, ProviderRecord

log = get_logger(__name__)

GATE_REASON = (
    "Observed prices are gated: no LOCALPRICE_API_KEY is configured and this is "
    "not a local environment, so no price may be fabricated (I1). Set "
    "LOCALPRICE_API_KEY for live observed prices, or ALLOW_MOCK_DATA=1 for an "
    "explicit demo deployment (see docs/LAUNCH_KEYS.md)."
)


class GatedPriceProvider:
    """Refuses to fabricate: returns an empty, declared-gap price list."""

    name = "gated-prices"

    def observed_prices(
        self,
        hs_code: str,
        market_iso2: str,
        limit: int = 10,
        product_name: str | None = None,
    ) -> list[ProviderRecord[ObservedPrice]]:
        log.warning(
            "observed_prices_gated",
            hs_code=hs_code,
            market=market_iso2,
            reason=GATE_REASON,
        )
        return []

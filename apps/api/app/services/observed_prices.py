"""Observed competitor prices — the paid local-price layer (Wave 3), deepen-gated (I5).

The observed-price layer is a PAID layer, so it runs ONLY inside the deepen
context. This mirrors the engine's structural guard: a fetch outside deepen
returns a skipped result and never calls the provider. Inside deepen it fetches
observed prices for a market and persists them onto the market snapshot; a price
is always an observed listing with its source, never fabricated (I1).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Product
from app.providers.registry import get_price_provider
from app.services import engine
from app.services.competitor_snapshot import build_snapshot

log = get_logger(__name__)

SKIPPED_OUTSIDE_DEEPEN = "paid_price_layer_outside_deepen"


def fetch_prices_for_market(db: Session, product: Product, market_iso2: str) -> dict:
    """Fetch + persist observed competitor prices for one market (deepen-only, I5)."""
    if not engine.deepen_active():
        # I5 — the paid layer never runs outside deepen; no provider call is made.
        log.info(
            "price_fetch_skipped_outside_deepen",
            product_id=str(product.id),
            market=market_iso2,
        )
        return {
            "market": market_iso2,
            "skipped": True,
            "reason": SKIPPED_OUTSIDE_DEEPEN,
            "count": 0,
        }

    # Pass the product NAME to the live shopping-search adapter — an HS6 code is
    # not a usable shopping query. Prefer the English name, fall back to Arabic.
    records = get_price_provider().observed_prices(
        product.hs_code,
        market_iso2,
        product_name=product.name_en or product.name_ar,
    )
    prices = [
        {
            "competitor": r.data.competitor,
            "price": r.data.price,
            "currency": r.data.currency,
            "url": r.data.url,
            "store": r.data.store,
            "source": r.provider_name,
        }
        for r in records
    ]
    snapshot = build_snapshot(db, product.hs_code, market_iso2)
    snapshot.observed_prices = prices
    db.flush()
    log.info("prices_fetched", product_id=str(product.id), market=market_iso2, count=len(prices))
    return {"market": market_iso2, "skipped": False, "count": len(prices)}

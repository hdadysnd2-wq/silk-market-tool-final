"""Margin threads — the factory's margin against each competitor's observed price.

Wave 3 part 2. Reuses the engine's zero-network ``correlation.correlate`` over the
observed prices the deepen price layer persisted. A competitor with no observed
price is declared "سعر غير مرصود"; with no product cost the margin itself is a
declared gap — never invented (I1).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarketSnapshot, Product

_NO_COST_NOTE = "أدخل تكلفة الوحدة (cost_per_unit) لحساب الهامش"


def compute_margin_threads(db: Session, product: Product, market_iso2: str) -> dict:
    """Competitor + margin threads for one market, from the persisted observed prices."""
    snapshot = db.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.hs_code == product.hs_code,
            MarketSnapshot.market_iso2 == market_iso2,
        )
    )
    observed = (snapshot.observed_prices if snapshot else None) or []
    cost = float(product.cost_per_unit) if product.cost_per_unit is not None else None

    # Map the persisted observed prices into the engine's correlation row shape:
    # the competitor name is used as both the named competitor and its priced
    # listing title, so correlate matches them exactly.
    row = {
        "competitors_named": [
            {"value": {"title": p["competitor"], "link": p.get("url")}} for p in observed
        ],
        "localprice": [
            {
                "value": {
                    "title": p["competitor"],
                    "price": p.get("price"),
                    "currency": p.get("currency"),
                    "store": p.get("store"),
                }
            }
            for p in observed
        ],
    }

    import correlation

    result = correlation.correlate(
        row,
        {"cost_per_unit": cost or 0.0, "shipping_per_unit": 0.0},
        product.name_en or product.name_ar or "",
    )
    competitor_threads = result.get("competitor_threads", [])
    # I1 — a margin needs the factory's own cost; without it, declare the gap
    # rather than surface the misleading 100% the raw computation would produce.
    margin_threads = result.get("feasibility_threads", []) if cost is not None else []

    return {
        "market": market_iso2,
        "cost_per_unit": cost,
        "cost_available": cost is not None,
        "competitor_threads": competitor_threads,
        "margin_threads": margin_threads,
        "note": None if cost is not None else _NO_COST_NOTE,
    }

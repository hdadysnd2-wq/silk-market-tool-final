"""Competitor margin thread — the exporter's headroom vs each observed price.

The DoD's "competitor lists with observed prices and margin threads (name +
observed price + computed margin)". This is the correlation/feasibility thread:
it runs with **zero external calls** (mirroring the engine's correlation rule),
operating only on the factory's own offer price and the observed competitor
prices already fetched by the deepen price layer (``MarketSnapshot.observed_prices``).

Every figure is computed or a **declared gap** (I1): a missing offer price, a
currency mismatch (no FX is invented), or a missing observed price yields
``margin_pct=None`` with a note — never a fabricated margin. The margin is a
*gross* headroom against the market price; tariff and freight are not included
(stated as a limit), so it is never presented as a landed-cost net margin.
"""

from __future__ import annotations

from statistics import median

from app.models import MarketSnapshot, Product


def _offer_midpoint(product: Product) -> float | None:
    """The factory's offer as the midpoint of its price band (None if unpriced)."""
    values = [float(v) for v in (product.price_min, product.price_max) if v is not None]
    return sum(values) / len(values) if values else None


def build_margin_thread(
    product: Product, market_iso2: str, snapshot: MarketSnapshot | None
) -> dict:
    """Build the margin thread for one product in one market as a JSON-safe dict."""
    offer = _offer_midpoint(product)
    offer_ccy = product.currency
    observed = (snapshot.observed_prices if snapshot else None) or []

    competitors: list[dict] = []
    margins: list[float] = []
    observed_values: list[float] = []
    currency_mismatch = False

    for row in observed:
        price = row.get("price")
        ccy = row.get("currency")
        margin: float | None = None
        note = ""
        if price is None:
            note = "no observed price"  # I1 — declared gap
        elif offer is None:
            note = "no factory offer price on file"
        elif ccy and offer_ccy and ccy != offer_ccy:
            note = f"currency mismatch ({ccy} vs {offer_ccy}) — no FX applied"
            currency_mismatch = True
        else:
            price_f = float(price)
            if price_f > 0:
                margin = round((price_f - offer) / price_f, 4)
                margins.append(margin)
                observed_values.append(price_f)
            else:
                note = "non-positive observed price"
        competitors.append(
            {
                "competitor": row.get("competitor"),
                "observed_price": float(price) if price is not None else None,
                "currency": ccy,
                "margin_pct": margin,
                "source": row.get("source"),
                "url": row.get("url"),
                "note": note,
            }
        )

    limits: list[str] = []
    if offer is None:
        limits.append(
            "No factory offer price on file — set the product's price to compute margins."
        )
    if not observed:
        limits.append(
            "No observed competitor prices yet — run the deepen price fetch for this market."
        )
    if currency_mismatch:
        limits.append(
            "Some competitor prices are in a different currency; no FX conversion is "
            "applied — those margins are shown as gaps (I1)."
        )
    # The margin is gross headroom against the market price, not a landed-cost net
    # margin — say so rather than overstate it.
    limits.append("Gross headroom vs the market price; tariff and freight are not included.")

    hs_code = product.hs_code
    src = snapshot.source if snapshot else "localprice"
    source_line = f"observed prices: {src}; offer: factory-declared"

    return {
        "hs_code": hs_code,
        "market_iso2": market_iso2,
        "factory_offer": offer,
        "factory_currency": offer_ccy,
        "median_observed_price": median(observed_values) if observed_values else None,
        "median_margin_pct": round(median(margins), 4) if margins else None,
        "competitors": competitors,
        "source_line": source_line,
        "limits": limits,
    }

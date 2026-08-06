"""Competitor margin thread — the exporter's headroom vs each observed price.

The DoD's "competitor lists with observed prices and margin threads (name +
observed price + computed margin)". This is the correlation/feasibility thread:
it runs with **zero external calls** (mirroring the engine's correlation rule),
operating only on the factory's own offer price and the observed competitor
prices already fetched by the deepen price layer (``MarketSnapshot.observed_prices``).

Every figure is computed or a **declared gap** (I1): a missing basis price, a
currency mismatch (no FX is invented), or a missing observed price yields
``margin_pct=None`` with a note — never a fabricated margin. Tariff and freight
are not included (stated as a limit), so it is never presented as a landed-cost
net margin.

**Margin basis.** When the factory has recorded a real ``cost_per_unit`` the
margin is a true gross margin against that actual cost; otherwise it falls back
to *gross headroom* against the offer-price midpoint (an estimate). The chosen
basis is reported in ``margin_basis`` and spelled out in the limits so the two
are never conflated (closed PR #39's distinct idea; see docs/BACKLOG.md).
"""

from __future__ import annotations

from statistics import median

from app.models import MarketSnapshot, Product


def _offer_midpoint(product: Product) -> float | None:
    """The factory's offer as the midpoint of its price band (None if unpriced)."""
    values = [float(v) for v in (product.price_min, product.price_max) if v is not None]
    return sum(values) / len(values) if values else None


def _margin_basis(product: Product) -> tuple[float | None, str | None]:
    """The value margins are computed against, preferring real cost over the estimate.

    Returns ``(basis_value, basis_kind)`` where ``basis_kind`` is ``"actual_cost"``
    when the factory recorded a per-unit cost, ``"offer_estimate"`` when only the
    offer band is on file, or ``None`` when neither is (a declared gap, I1).
    """
    if product.cost_per_unit is not None:
        return float(product.cost_per_unit), "actual_cost"
    offer = _offer_midpoint(product)
    if offer is not None:
        return offer, "offer_estimate"
    return None, None


def build_margin_thread(
    product: Product, market_iso2: str, snapshot: MarketSnapshot | None
) -> dict:
    """Build the margin thread for one product in one market as a JSON-safe dict."""
    offer = _offer_midpoint(product)
    basis_value, basis_kind = _margin_basis(product)
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
        elif basis_value is None:
            note = "no factory cost or offer price on file"
        elif ccy and offer_ccy and ccy != offer_ccy:
            note = f"currency mismatch ({ccy} vs {offer_ccy}) — no FX applied"
            currency_mismatch = True
        else:
            price_f = float(price)
            if price_f > 0:
                margin = round((price_f - basis_value) / price_f, 4)
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
    if basis_value is None:
        limits.append(
            "No factory cost or offer price on file — set a per-unit cost or a price "
            "band to compute margins."
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
    # Spell out the basis so a real margin and an offer-estimate headroom are never
    # conflated — and never overstate either as a landed-cost net margin.
    if basis_kind == "actual_cost":
        limits.append(
            "Gross margin vs the factory's actual per-unit cost; tariff and freight "
            "are not included."
        )
    else:
        limits.append(
            "Gross headroom vs the offer-price estimate (no per-unit cost on file); "
            "tariff and freight are not included."
        )

    cost = float(product.cost_per_unit) if product.cost_per_unit is not None else None
    hs_code = product.hs_code
    src = snapshot.source if snapshot else "localprice"
    basis_desc = {
        "actual_cost": "actual factory cost",
        "offer_estimate": "offer-price estimate",
    }.get(basis_kind, "none on file")
    source_line = f"observed prices: {src}; margin basis: {basis_desc}"

    return {
        "hs_code": hs_code,
        "market_iso2": market_iso2,
        "factory_offer": offer,
        "cost_per_unit": cost,
        "margin_basis": basis_kind,
        "factory_currency": offer_ccy,
        "median_observed_price": median(observed_values) if observed_values else None,
        "median_margin_pct": round(median(margins), 4) if margins else None,
        "competitors": competitors,
        "source_line": source_line,
        "limits": limits,
    }

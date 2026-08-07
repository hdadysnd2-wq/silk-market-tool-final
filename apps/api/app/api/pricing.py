"""Deepen path: observed competitor prices (paid local-price layer, I5-gated)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbDep, get_owned_product
from app.models import MarketSnapshot, Product
from app.schemas.buyer import MarginThreadOut
from app.security import CurrentUser
from app.services import engine, observed_prices, rate_limit
from app.services.api_budget import budget_scope
from app.services.margin import build_margin_thread

router = APIRouter(tags=["pricing"])

# Fan-out guards for the paid observed-price layer (C17 + C14). Each market in the
# request triggers one synchronous paid SerpApi price fetch, so an unbounded loop
# would drain the paid key even with SILK_PAID_DAILY_CAP set. A small per-user
# hourly cap blunts cross-request enumeration; the reservation below enforces the
# daily paid budget per call.
DEEPEN_PRICES_RATE_LIMIT = 10  # paid price runs per user per hour
DEEPEN_PRICES_WINDOW_SECONDS = 3600
MAX_DEEPEN_MARKETS = 5  # one paid provider call per market — keep the fan-out small


class PricesRequest(BaseModel):
    markets: list[str]


@router.post("/products/{product_id}/deepen/prices")
def deepen_prices(
    payload: PricesRequest,
    db: DbDep,
    user: CurrentUser,
    product: Product = Depends(get_owned_product),
) -> dict:
    """Fetch observed competitor prices for the given markets (deepen / paid).

    I2 — like buyer discovery, the paid price layer runs only on a human-confirmed
    HS code. I5 — the fetch is permitted ONLY inside the deepen scope, re-established
    here explicitly (contextvars do not cross into a worker; the same guard holds
    in-process for this synchronous path).
    """
    # C17 + C14 — this is a *paid* fan-out (one SerpApi price fetch per market run
    # synchronously). Rate-limit per user so a loop can't drain the paid key across
    # requests (the daily cap alone can be burned in one burst).
    rate_limit.check(
        f"deepen_prices:{user.id}",
        limit=DEEPEN_PRICES_RATE_LIMIT,
        window_seconds=DEEPEN_PRICES_WINDOW_SECONDS,
    )
    if not (product.hs_code and product.hs_confirmed_by_user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HS code must be confirmed before fetching competitor prices",
        )

    # Normalize (dedupe + upper-case) then cap the fan-out — reject rather than
    # silently slice so the caller sees the limit explicitly.
    markets: list[str] = []
    for raw in payload.markets:
        m = raw.strip().upper()
        if m and m not in markets:
            markets.append(m)
    if len(markets) > MAX_DEEPEN_MARKETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many markets (max {MAX_DEEPEN_MARKETS})",
        )

    # Reserve the paid spend up front — one SerpApi call per market — against the
    # engine's daily paid-call cap (SILK_PAID_DAILY_CAP), mirroring the classifier's
    # reservation. Over the cap: refuse before any provider call is made. Lazy-import
    # keeps the router importable offline/keyless.
    import silk_usage

    if markets and not silk_usage.try_reserve_paid_calls(len(markets)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="daily paid-call cap reached",
        )

    results = []
    # Meter the live Comtrade snapshot calls this fetch triggers against the same
    # per-analysis budget ceiling the worker paths use (decision #5).
    with budget_scope(label=f"deepen_prices:{product.id}"), engine.deepen_scope(True):
        for market in markets:
            results.append(observed_prices.fetch_prices_for_market(db, product, market))
    db.commit()
    return {"detail": "Observed prices fetched", "results": results}


@router.get("/products/{product_id}/markets/{market}/margin", response_model=MarginThreadOut)
def market_margin(
    market: str,
    db: DbDep,
    product: Product = Depends(get_owned_product),
) -> MarginThreadOut:
    """The competitor margin thread for one market: name + observed price + margin.

    A pure read/compute over the factory's offer and the observed prices already
    fetched by the deepen layer (no external calls, no deepen needed). When no
    prices have been fetched, the thread returns with the gap declared in its
    limits rather than an error — never a fabricated margin (I1).
    """
    market = market.upper()
    snapshot = None
    if product.hs_code:
        snapshot = db.scalar(
            select(MarketSnapshot).where(
                MarketSnapshot.hs_code == product.hs_code,
                MarketSnapshot.market_iso2 == market,
            )
        )
    return MarginThreadOut.model_validate(build_margin_thread(product, market, snapshot))

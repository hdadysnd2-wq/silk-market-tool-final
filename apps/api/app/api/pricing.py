"""Deepen path: observed competitor prices (paid local-price layer, I5-gated)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import DbDep, get_owned_product
from app.models import Product
from app.services import engine, observed_prices

router = APIRouter(tags=["pricing"])


class PricesRequest(BaseModel):
    markets: list[str]


@router.post("/products/{product_id}/deepen/prices")
def deepen_prices(
    payload: PricesRequest,
    db: DbDep,
    product: Product = Depends(get_owned_product),
) -> dict:
    """Fetch observed competitor prices for the given markets (deepen / paid).

    I2 — like buyer discovery, the paid price layer runs only on a human-confirmed
    HS code. I5 — the fetch is permitted ONLY inside the deepen scope, re-established
    here explicitly (contextvars do not cross into a worker; the same guard holds
    in-process for this synchronous path).
    """
    if not (product.hs_code and product.hs_confirmed_by_user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HS code must be confirmed before fetching competitor prices",
        )

    results = []
    with engine.deepen_scope(True):
        for market in payload.markets:
            results.append(observed_prices.fetch_prices_for_market(db, product, market.upper()))
    db.commit()
    return {"detail": "Observed prices fetched", "results": results}

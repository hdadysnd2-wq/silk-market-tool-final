"""Buyer discovery kick-off and ranked buyer listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbDep, get_owned_product
from app.models import Contact, Product
from app.schemas.buyer import BuyerMatchOut, BuyerOut, ContactOut, DiscoverRequest
from app.services.buyer_discovery import buyers_for_product
from app.workers.tasks import run_discovery

router = APIRouter(tags=["buyers"])


@router.post("/products/{product_id}/discover", status_code=status.HTTP_202_ACCEPTED)
def discover(
    payload: DiscoverRequest,
    db: DbDep,
    product: Product = Depends(get_owned_product),
) -> dict:
    if not product.hs_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm the product's HS code before discovering buyers",
        )
    markets = [m.upper() for m in payload.markets]
    # Enqueue one discovery job per market. In eager mode (tests / local worker
    # off) these run synchronously.
    for market in markets:
        run_discovery.delay(str(product.id), market)
    return {"detail": "Discovery started", "markets": markets}


@router.get("/products/{product_id}/buyers", response_model=list[BuyerMatchOut])
def list_buyers(
    db: DbDep,
    market: str | None = None,
    product: Product = Depends(get_owned_product),
) -> list[BuyerMatchOut]:
    pairs = buyers_for_product(db, product.id, market.upper() if market else None)
    results: list[BuyerMatchOut] = []
    for match, buyer in pairs:
        contacts = db.scalars(select(Contact).where(Contact.buyer_id == buyer.id)).all()
        results.append(
            BuyerMatchOut(
                buyer=BuyerOut.model_validate(buyer),
                market_iso2=match.market_iso2,
                relevance_score=match.relevance_score,
                score_breakdown=match.score_breakdown,
                evidence=match.evidence,
                contacts=[ContactOut.model_validate(c) for c in contacts],
            )
        )
    return results

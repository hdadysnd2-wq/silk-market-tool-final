"""Buyer discovery kick-off and ranked buyer listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbDep, get_owned_product
from app.models import Contact, Product
from app.schemas.buyer import BuyerMatchOut, BuyerOut, ContactOut, DiscoverRequest
from app.services import lead_validity
from app.services.buyer_discovery import buyers_for_product
from app.workers.tasks import run_discovery

router = APIRouter(tags=["buyers"])


@router.post("/products/{product_id}/discover", status_code=status.HTTP_202_ACCEPTED)
def discover(
    payload: DiscoverRequest,
    db: DbDep,
    product: Product = Depends(get_owned_product),
) -> dict:
    # I2 — buyer discovery fetches buyer PII, so it runs only on a *human-confirmed*
    # HS code. The classifier pre-fills product.hs_code with its top candidate
    # before the user confirms, so checking hs_code alone would let discovery run
    # on a guess; the confirmation flag is the real gate (as on the analysis run).
    if not (product.hs_code and product.hs_confirmed_by_user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HS code must be confirmed before discovering buyers",
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
        buyer_out = BuyerOut.model_validate(buyer)
        # Rule 6 / I8 — stamp the 90-day validity window and flag stale leads so a
        # human sees an explicit warning rather than treating old data as current.
        buyer_out.valid_until = lead_validity.valid_until(buyer.freshness_at)
        buyer_out.is_stale = lead_validity.is_stale(buyer.freshness_at)
        results.append(
            BuyerMatchOut(
                buyer=buyer_out,
                market_iso2=match.market_iso2,
                relevance_score=match.relevance_score,
                score_breakdown=match.score_breakdown,
                evidence=match.evidence,
                lawful_basis=match.lawful_basis,
                basis_note=match.basis_note,
                contacts=[ContactOut.model_validate(c) for c in contacts],
            )
        )
    return results

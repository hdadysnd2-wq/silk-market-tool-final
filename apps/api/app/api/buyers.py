"""Buyer discovery kick-off and ranked buyer listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbDep, get_owned_product
from app.models import Analysis, Contact, Product
from app.schemas.buyer import BuyerMatchOut, BuyerOut, ContactOut, DiscoverRequest
from app.security import CurrentUser
from app.services import lead_validity, rate_limit
from app.services.buyer_discovery import buyers_for_product
from app.workers.tasks import run_discovery

router = APIRouter(tags=["buyers"])

# Fan-out guard for buyer discovery (C18). Each market enqueues one paid
# run_discovery job, so an unbounded/unvalidated markets list lets a single
# request kick off an arbitrary number of paid runs. Rate-limit per user and cap
# the list. (Per-provider budget metering inside run_discovery is a documented
# follow-up owned by app/workers/tasks.py — not attempted here.)
DISCOVER_RATE_LIMIT = 20  # discovery kickoffs per user per hour
DISCOVER_WINDOW_SECONDS = 3600
MAX_DISCOVER_MARKETS = 5  # one paid discovery run enqueued per market


@router.post("/products/{product_id}/discover", status_code=status.HTTP_202_ACCEPTED)
def discover(
    payload: DiscoverRequest,
    db: DbDep,
    user: CurrentUser,
    product: Product = Depends(get_owned_product),
) -> dict:
    # C18 — discovery enqueues one paid run_discovery per market. Rate-limit per
    # user so one request (or a loop of them) can't fan out into an unbounded
    # number of paid runs.
    rate_limit.check(
        f"discover:{user.id}",
        limit=DISCOVER_RATE_LIMIT,
        window_seconds=DISCOVER_WINDOW_SECONDS,
    )
    # I2 (ADR-0009) — buyer discovery fetches buyer PII, so it runs only on a
    # COMMITTED HS code: human-confirmed, or the engine's strict auto commit.
    # hs_ready is the one gate predicate; checking hs_code alone would let
    # discovery run on an uncommitted proposal.
    if not product.hs_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HS code must be confirmed before discovering buyers",
        )
    # Normalize (dedupe + upper-case) then cap the fan-out — reject an oversized
    # list rather than silently truncating it.
    markets: list[str] = []
    for raw in payload.markets:
        m = raw.strip().upper()
        if m and m not in markets:
            markets.append(m)
    if len(markets) > MAX_DISCOVER_MARKETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many markets (max {MAX_DISCOVER_MARKETS})",
        )
    # Decision #6 / I8 — a lead fetch is bound to a specific analysis, never a
    # free-standing bulk pull. Discovery therefore requires an analysis for this
    # product and stamps every match with its id.
    analysis = db.scalar(
        select(Analysis)
        .where(Analysis.product_id == product.id)
        .order_by(Analysis.created_at.desc())
        .limit(1)
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run a market analysis first — lead discovery is bound to an analysis",
        )
    # Enqueue one discovery job per market. In eager mode (tests / local worker
    # off) these run synchronously.
    for market in markets:
        run_discovery.delay(str(product.id), market, str(analysis.id))
    return {"detail": "Discovery started", "markets": markets, "analysis_id": str(analysis.id)}


@router.get("/products/{product_id}/buyers", response_model=list[BuyerMatchOut])
def list_buyers(
    db: DbDep,
    market: str | None = None,
    limit: int = 50,
    offset: int = 0,
    product: Product = Depends(get_owned_product),
) -> list[BuyerMatchOut]:
    # Bounded page (audit H2): the buyers view is polled every few seconds and a
    # single market can hold ~220 buyers — an unpaginated list was hundreds of
    # rows per poll per user. Clamp to a sane page and slice deterministically
    # (buyers_for_product already orders by score desc).
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    # LIMIT/OFFSET are pushed into SQL (audit H2) — the DB returns just this page
    # rather than every match row for the market being sliced in Python.
    pairs = buyers_for_product(
        db, product.id, market.upper() if market else None, limit=limit, offset=offset
    )

    # Batch-load contacts for the page's buyers in ONE query instead of one per
    # buyer (the N+1 the audit flagged).
    buyer_ids = [buyer.id for _match, buyer in pairs]
    contacts_by_buyer: dict[object, list[Contact]] = {}
    if buyer_ids:
        for contact in db.scalars(select(Contact).where(Contact.buyer_id.in_(buyer_ids))).all():
            contacts_by_buyer.setdefault(contact.buyer_id, []).append(contact)

    results: list[BuyerMatchOut] = []
    for match, buyer in pairs:
        contacts = contacts_by_buyer.get(buyer.id, [])
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
                analysis_id=match.analysis_id,
                contacts=[ContactOut.model_validate(c) for c in contacts],
            )
        )
    return results

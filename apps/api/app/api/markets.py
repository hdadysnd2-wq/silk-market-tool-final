"""Markets list and competitor snapshots."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbDep
from app.models import Market
from app.schemas.buyer import CompetitorSnapshotOut
from app.schemas.common import MarketOut
from app.security import CurrentUser
from app.services import rate_limit
from app.services.api_budget import budget_scope
from app.services.competitor_snapshot import build_snapshot

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("", response_model=list[MarketOut])
def list_markets(db: DbDep, user: CurrentUser) -> list[MarketOut]:
    rows = db.scalars(select(Market).order_by(Market.name_en)).all()
    return [MarketOut.model_validate(m) for m in rows]


@router.get("/{iso2}/competitors", response_model=CompetitorSnapshotOut)
def competitors(iso2: str, hs_code: str, db: DbDep, user: CurrentUser) -> CompetitorSnapshotOut:
    # Two guards on the interactive snapshot, which can trigger live Comtrade:
    # 1) A per-user rate limit. The budget_scope below caps live calls WITHIN one
    #    request, but that scope resets per request — so on its own it can't stop a
    #    user from enumerating many (hs, iso2) pairs across requests to drain the
    #    key. A per-user sliding window blunts that enumeration (each snapshot can
    #    trigger up to 3 live Comtrade calls).
    rate_limit.check(f"competitors:{user.id}", limit=30, window_seconds=300)
    # 2) A budget scope, so those live calls charge the same per-analysis ceiling
    #    the worker paths use — without a scope, api_budget.charge is unmetered
    #    (decision #5's ≤150/analysis ceiling).
    with budget_scope(label=f"competitors:{iso2.upper()}:{hs_code}"):
        snapshot = build_snapshot(db, hs_code, iso2.upper())
    db.commit()
    return CompetitorSnapshotOut(
        hs_code=snapshot.hs_code,
        market_iso2=snapshot.market_iso2,
        total_import_usd=float(snapshot.total_import_usd) if snapshot.total_import_usd else None,
        trend_pct=float(snapshot.trend_pct) if snapshot.trend_pct is not None else None,
        top_exporters=snapshot.top_exporters,
        yearly_values=snapshot.yearly_values,
        observed_prices=snapshot.observed_prices,
        source=snapshot.source,
    )

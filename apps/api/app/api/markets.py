"""Markets list and competitor snapshots."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbDep
from app.models import Market
from app.schemas.buyer import CompetitorSnapshotOut
from app.schemas.common import MarketOut
from app.security import CurrentUser
from app.services.competitor_snapshot import build_snapshot

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("", response_model=list[MarketOut])
def list_markets(db: DbDep, user: CurrentUser) -> list[MarketOut]:
    rows = db.scalars(select(Market).order_by(Market.name_en)).all()
    return [MarketOut.model_validate(m) for m in rows]


@router.get("/{iso2}/competitors", response_model=CompetitorSnapshotOut)
def competitors(iso2: str, hs_code: str, db: DbDep, user: CurrentUser) -> CompetitorSnapshotOut:
    snapshot = build_snapshot(db, hs_code, iso2.upper())
    db.commit()
    return CompetitorSnapshotOut(
        hs_code=snapshot.hs_code,
        market_iso2=snapshot.market_iso2,
        total_import_usd=float(snapshot.total_import_usd) if snapshot.total_import_usd else None,
        trend_pct=float(snapshot.trend_pct) if snapshot.trend_pct is not None else None,
        top_exporters=snapshot.top_exporters,
        yearly_values=snapshot.yearly_values,
        source=snapshot.source,
    )

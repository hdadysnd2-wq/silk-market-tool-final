"""Persist the world-funnel country rankings for an analysis (funnel Stage 1).

Runs the local Stage-1 screen (``services.world_funnel.screen_world``) for a
confirmed HS6 and stores the ranked shortlist against the analysis — the
"world screened → top 5" the report surfaces. Each row keeps the transit-port /
mirror / no-data provenance tags (I9 / I1) that set its rank. Stage 2/3
enrichment of the shortlist lands in later increments.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Analysis, CountryRanking
from app.services.world_funnel import screen_world

log = get_logger(__name__)


def rank_and_persist(
    db: Session, analysis: Analysis, hs6: str, top_n: int = 20
) -> list[CountryRanking]:
    """Screen the world for ``hs6`` and persist the ranked shortlist to ``analysis``.

    Returns the persisted ``CountryRanking`` rows (rank 1..N). The transit-port
    guard (I9) and provenance tags come straight from the screen — a re-export hub
    is stored flagged and penalized, never silently on top; a no-data market is a
    declared gap (I1).
    """
    result = screen_world(db, hs6, top_n=top_n)
    rankings: list[CountryRanking] = []
    for rank, m in enumerate(result.markets, start=1):
        cr = CountryRanking(
            analysis_id=analysis.id,
            rank=rank,
            importer_iso3=m.importer_iso3,
            year=m.year,
            import_usd=m.import_usd,
            yoy_growth=m.yoy_growth,
            cagr_3y=m.cagr_3y,
            screen_score=m.screen_score,
            is_transit_hub=m.is_transit_hub,
            is_mirror=m.is_mirror,
            tags=list(m.tags),
            stage=1,
            source="world_trade",
        )
        db.add(cr)
        rankings.append(cr)
    db.flush()
    log.info(
        "country_rankings_persisted",
        analysis_id=str(analysis.id),
        hs6=hs6,
        screened=result.total_screened,
        ranked=len(rankings),
    )
    return rankings

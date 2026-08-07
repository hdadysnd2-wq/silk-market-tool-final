"""Persist the world-funnel country rankings for an analysis (funnel Stage 1).

Runs the local Stage-1 screen (``services.world_funnel.screen_world``) for a
confirmed HS6 and stores the ranked shortlist against the analysis — the
"world screened → top 5" the report surfaces. Each row keeps the transit-port /
mirror / no-data provenance tags (I9 / I1) that set its rank. Stage 2/3
enrichment of the shortlist lands in later increments.
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Analysis, CountryRanking, Product
from app.services.world_funnel import screen_world

log = get_logger(__name__)


def run_product_world_analysis(db: Session, product: Product, top_n: int | None = None) -> Analysis:
    """Create an analysis for a product and persist its world-funnel ranking.

    The caller MUST ensure the product's HS code is human-confirmed (I2) — this
    runs the world screen on ``product.hs_code`` and never re-classifies. Returns
    the persisted ``Analysis`` (status ``ranked``) with its ``country_rankings``.
    """
    name = product.name_en or product.name_ar
    analysis = Analysis(product_id=product.id, product_name=name, status="classified")
    db.add(analysis)
    db.flush()
    rank_and_persist(db, analysis, product.hs_code, top_n=top_n)
    analysis.status = "ranked"
    db.flush()
    return analysis


def rank_and_persist(
    db: Session, analysis: Analysis, hs6: str, top_n: int | None = None
) -> list[CountryRanking]:
    """Screen the world for ``hs6`` and persist the ranked shortlist to ``analysis``.

    Returns the persisted ``CountryRanking`` rows (rank 1..N). ``top_n=None``
    (the default) applies the top-20% cut (``world_funnel.shortlist_quota`` —
    ceil(20%) of covered markets, clamped to [5, 30]). The transit-port
    guard (I9) and provenance tags come straight from the screen — a re-export hub
    is stored flagged and penalized, never silently on top; a no-data market is a
    declared gap (I1).
    """
    result = screen_world(db, hs6, top_n=top_n)
    # Idempotency (C1): task_acks_late + task_reject_on_worker_lost mean a worker
    # lost AFTER the commit but BEFORE the Celery ack redelivers run_world_ranking.
    # With no delete-first and no unique constraint, a second run would INSERT a
    # full DUPLICATE set of CountryRanking rows — duplicated markets would then flow
    # into Stage 2, the executive report, and GET /analyses/{id}. Delete any
    # existing rows for this analysis in the SAME transaction so a redelivery
    # REPLACES the shortlist rather than duplicating it.
    db.execute(delete(CountryRanking).where(CountryRanking.analysis_id == analysis.id))
    # Funnel transparency: record the full world count screened AND how many the
    # top-20% cut kept, so the report can show "screened N → shortlisted M → top 5".
    analysis.total_screened = result.total_screened
    analysis.shortlisted = result.shortlisted
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

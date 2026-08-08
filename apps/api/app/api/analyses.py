"""Analysis runs — drive the world-funnel pipeline for a confirmed product.

``POST /products/{id}/analysis`` runs the world funnel (Stage 1) for a product
whose HS code has been human-confirmed (I2) and persists the ranked country
shortlist ("world screened → top 5", transit-flagged). ``GET /analyses/{id}``
returns a run with its rankings.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbDep, get_owned_product
from app.models import Analysis, CountryRanking, Product
from app.models.product import Product as ProductModel
from app.providers.countries import iso3_to_iso2
from app.schemas.analysis import AnalysisAccepted, AnalysisOut, CountryRankingOut, FunnelBriefOut
from app.security import CurrentUser, assert_factory_access
from app.services.funnel_brief import build_funnel_brief
from app.services.ranking_rationale import build_rationale
from app.workers.tasks import run_stage2_enrich, run_stage3_deepdive, run_world_ranking

router = APIRouter(tags=["analyses"])

#: Top-N rows that carry the one-line "why this market ranked" rationale (J1).
_RATIONALE_TOP_N = 5


def _ranking_out(r: CountryRanking) -> CountryRankingOut:
    out = CountryRankingOut.model_validate(r)
    # Bridge the funnel's alpha-3 to the alpha-2 the competitor/buyer flow uses,
    # so the top-5 can drill into each country's deep-dive. None for an unknown
    # market — a declared gap, never a fabricated code (I1).
    out.market_iso2 = iso3_to_iso2(r.importer_iso3)
    # J1 transparency — computed on read from the persisted score components
    # (nothing new stored): the top-5 rows each carry a deterministic one-liner
    # naming the two heaviest components with their real values and sources.
    # Rows without scored components (Stage-1-only runs) stay None (I1).
    if r.rank <= _RATIONALE_TOP_N:
        rationale = build_rationale((r.enrichment or {}).get("score_components"))
        if rationale is not None:
            out.rationale_en = rationale["en"]
            out.rationale_ar = rationale["ar"]
    return out


def _to_out(db: DbDep, analysis: Analysis) -> AnalysisOut:
    rankings = db.scalars(
        select(CountryRanking)
        .where(CountryRanking.analysis_id == analysis.id)
        .order_by(CountryRanking.rank)
    ).all()
    out = AnalysisOut.model_validate(analysis)
    out.rankings = [_ranking_out(r) for r in rankings]
    return out


@router.post(
    "/products/{product_id}/analysis",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_analysis(
    db: DbDep,
    product: ProductModel = Depends(get_owned_product),
) -> AnalysisAccepted:
    # I2 (ADR-0009) — the world funnel runs only on a COMMITTED HS code (human
    # confirm, or the engine's strict auto commit). An uncommitted or missing
    # code is a 409, never a silent run on a guessed code.
    if not product.hs_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HS code must be confirmed before running a world analysis",
        )
    # Create the spine record as pending and commit FIRST so the (eager or real)
    # ranking task can load it in its own session; the task does the Stage-1 screen.
    analysis = Analysis(
        product_id=product.id,
        product_name=product.name_en or product.name_ar,
        status="pending",
    )
    db.add(analysis)
    db.commit()

    # Snapshot the pending analysis for the 202 body BEFORE enqueuing (eager mode
    # would otherwise bleed the ranked result in). The client polls GET for it.
    accepted = _to_out(db, analysis)
    task = run_world_ranking.delay(str(analysis.id), product.hs_code)
    return AnalysisAccepted(task_id=task.id, analysis=accepted)


def _owned_analysis(db: DbDep, analysis_id: uuid.UUID, user: CurrentUser) -> Analysis:
    """Load an analysis, authorized via the owning product's factory.

    An orphaned analysis (product deleted) cannot be authorized and is treated as
    not found.
    """
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    product = db.get(Product, analysis.product_id) if analysis.product_id else None
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    assert_factory_access(user, product.factory_id)
    return analysis


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: uuid.UUID, db: DbDep, user: CurrentUser) -> AnalysisOut:
    return _to_out(db, _owned_analysis(db, analysis_id, user))


@router.get("/analyses/{analysis_id}/brief", response_model=FunnelBriefOut)
def get_analysis_brief(analysis_id: uuid.UUID, db: DbDep, user: CurrentUser) -> FunnelBriefOut:
    """Brief-first funnel output: decision + 3 sourced numbers + a limits section."""
    analysis = _owned_analysis(db, analysis_id, user)
    return FunnelBriefOut.model_validate(build_funnel_brief(db, analysis))


@router.post(
    "/analyses/{analysis_id}/enrich",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def enrich_analysis(analysis_id: uuid.UUID, db: DbDep, user: CurrentUser) -> AnalysisAccepted:
    """Funnel Stage 2: budgeted enrichment of the Stage-1 shortlist → top 5.

    Enqueues the enrichment task, which enriches the persisted shortlist with
    applied-tariff + PPP signals under the per-analysis API budget (decision #5)
    and re-ranks to the top 5. Returns 202 immediately; the client polls
    ``GET /analyses/{id}`` for the enriched result once the task finishes.
    """
    analysis = _owned_analysis(db, analysis_id, user)
    product = db.get(Product, analysis.product_id) if analysis.product_id else None
    # I2 (ADR-0009) — never enrich/rank on an uncommitted HS code.
    if not (product and product.hs_ready):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HS code must be confirmed before Stage-2 enrichment",
        )
    # C2 — Stage 2 must not run before Stage 1 has committed a ranking. Gate on the
    # analysis status too (not just HS confirmation): enriching a 'pending' /
    # 'classified' / 'failed' analysis would produce an 'enriched' run with zero
    # rankings. Only a ranked-or-later analysis may be (re-)enriched.
    if analysis.status not in ("ranked", "enriched", "deepened"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "analysis must be ranked before Stage-2 enrichment "
                f"(current status: {analysis.status})"
            ),
        )
    # Snapshot the pre-enrich analysis for the 202 body BEFORE enqueuing (eager mode
    # would otherwise bleed the re-ranked Stage-2 result in).
    accepted = _to_out(db, analysis)
    task = run_stage2_enrich.delay(str(analysis_id), product.hs_code)
    return AnalysisAccepted(task_id=task.id, analysis=accepted)


@router.post(
    "/analyses/{analysis_id}/deepdive",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def deepdive_analysis(analysis_id: uuid.UUID, db: DbDep, user: CurrentUser) -> AnalysisAccepted:
    """Funnel Stage 3: FREE per-market deep-dive of the top-5 finalists (manual re-run).

    Stage 3 auto-chains after Stage-2 enrichment; this endpoint re-runs it on
    demand. Enqueues the deep-dive task, which annotates each finalist with the
    engine's FREE offline layers (competitors, requirements checklist, correlation
    threads) and marks the analysis ``deepened``. Returns 202 immediately; the
    client polls ``GET /analyses/{id}`` for the deep-dived result.
    """
    analysis = _owned_analysis(db, analysis_id, user)
    product = db.get(Product, analysis.product_id) if analysis.product_id else None
    # I2 (ADR-0009) — never deep-dive on an uncommitted HS code.
    if not (product and product.hs_ready):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HS code must be confirmed before Stage-3 deep-dive",
        )
    # C2 — Stage 3 runs on the Stage-2 finalists, so it must not run before Stage 2
    # has committed an enriched shortlist. Only an enriched-or-already-deepened
    # analysis may be (re-)deep-dived.
    if analysis.status not in ("enriched", "deepened"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "analysis must be enriched before Stage-3 deep-dive "
                f"(current status: {analysis.status})"
            ),
        )
    # Snapshot the pre-deepdive analysis for the 202 body BEFORE enqueuing (eager
    # mode would otherwise bleed the deep-dived result in).
    accepted = _to_out(db, analysis)
    task = run_stage3_deepdive.delay(str(analysis_id), product.hs_code)
    return AnalysisAccepted(task_id=task.id, analysis=accepted)

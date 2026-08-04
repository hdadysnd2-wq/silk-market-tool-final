"""Analysis runs — drive the world-funnel pipeline for a confirmed product.

``POST /products/{id}/analysis`` runs the world funnel (Stage 1) for a product
whose HS code has been human-confirmed (I2) and persists the ranked country
shortlist ("world screened → top 5", transit-flagged). ``GET /analyses/{id}``
returns a run with its rankings.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbDep, get_owned_product
from app.models import Analysis, CountryRanking, Product
from app.models.product import Product as ProductModel
from app.providers.countries import iso3_to_iso2
from app.schemas.analysis import AnalysisOut, CountryRankingOut, FunnelBriefOut
from app.security import CurrentUser, assert_factory_access
from app.services.api_budget import budget_scope
from app.services.funnel_brief import build_funnel_brief
from app.services.ranking import run_product_world_analysis
from app.services.stage2 import enrich_shortlist

router = APIRouter(tags=["analyses"])


def _ranking_out(r: CountryRanking) -> CountryRankingOut:
    out = CountryRankingOut.model_validate(r)
    # Bridge the funnel's alpha-3 to the alpha-2 the competitor/buyer flow uses,
    # so the top-5 can drill into each country's deep-dive. None for an unknown
    # market — a declared gap, never a fabricated code (I1).
    out.market_iso2 = iso3_to_iso2(r.importer_iso3)
    return out


def _to_out(db: DbDep, analysis: Analysis) -> AnalysisOut:
    rankings = (
        db.query(CountryRanking)
        .filter(CountryRanking.analysis_id == analysis.id)
        .order_by(CountryRanking.rank)
        .all()
    )
    out = AnalysisOut.model_validate(analysis)
    out.rankings = [_ranking_out(r) for r in rankings]
    return out


@router.post(
    "/products/{product_id}/analysis",
    response_model=AnalysisOut,
    status_code=status.HTTP_201_CREATED,
)
def start_analysis(
    db: DbDep,
    product: ProductModel = Depends(get_owned_product),
) -> AnalysisOut:
    # I2 — the world funnel runs only on a human-confirmed HS code. An unconfirmed
    # or missing code is a 409, never a silent run on a guessed code.
    if not (product.hs_code and product.hs_confirmed_by_user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HS code must be confirmed before running a world analysis",
        )
    analysis = run_product_world_analysis(db, product)
    db.commit()
    return _to_out(db, analysis)


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


@router.post("/analyses/{analysis_id}/enrich", response_model=AnalysisOut)
def enrich_analysis(analysis_id: uuid.UUID, db: DbDep, user: CurrentUser) -> AnalysisOut:
    """Funnel Stage 2: budgeted enrichment of the Stage-1 shortlist → top 5.

    Enriches the persisted shortlist with applied-tariff + PPP signals under the
    per-analysis API budget (decision #5) and re-ranks to the top 5. The enrichment
    is budgeted/paid, so it is an explicit step; the Stage-1 screen stays free. A
    market whose enrichment fails keeps its Stage-1 score (a declared gap, I1).
    """
    analysis = _owned_analysis(db, analysis_id, user)
    product = db.get(Product, analysis.product_id) if analysis.product_id else None
    # I2 — never enrich/rank on an unconfirmed HS code.
    if not (product and product.hs_code and product.hs_confirmed_by_user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HS code must be confirmed before Stage-2 enrichment",
        )
    with budget_scope(label=f"stage2:{analysis_id}"):
        enrich_shortlist(db, analysis, product.hs_code)
    if analysis.status in ("pending", "classified", "ranked"):
        analysis.status = "enriched"
    db.commit()
    return _to_out(db, analysis)

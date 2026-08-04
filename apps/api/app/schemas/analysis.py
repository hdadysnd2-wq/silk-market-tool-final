"""API schemas for analysis runs and their world-funnel country rankings."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CountryRankingOut(BaseModel):
    rank: int
    importer_iso3: str
    #: The alpha-2 code the market/competitor machinery uses; None for a market
    #: we hold no alpha-2 reference for (a declared gap, never fabricated — I1).
    market_iso2: str | None = None
    year: int | None
    import_usd: float | None
    yoy_growth: float | None
    cagr_3y: float | None
    screen_score: float
    is_transit_hub: bool
    is_mirror: bool
    tags: list[str] | None
    stage: int
    #: Stage-2 re-ranking score + enrichment signals (None until Stage 2 runs).
    stage2_score: float | None = None
    enrichment: dict | None = None

    model_config = {"from_attributes": True}


class BriefFigureOut(BaseModel):
    """One decisive number with its provenance — the source line is never omitted."""

    label: str
    value: str | None  # None = a declared gap (I1), never a fabricated number
    source: str
    year: int | None


class FunnelBriefOut(BaseModel):
    """The brief-first funnel output (decision #7): decision + 3 numbers + limits."""

    analysis_id: str
    hs_code: str | None
    decision: str
    decisive_numbers: list[BriefFigureOut]
    competitive_position: list[str]
    limits: list[str]


class AnalysisOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    product_name: str
    status: str
    deepen: bool
    created_at: datetime
    #: Markets screened worldwide in Stage 1 — the real world count behind the
    #: funnel ("screened N → shortlisted M → top 5"). None for older runs.
    total_screened: int | None = None
    #: The world-funnel shortlist ("world screened → top 5"), transit-flagged.
    rankings: list[CountryRankingOut] = []

    model_config = {"from_attributes": True}


class AnalysisAccepted(BaseModel):
    """202 envelope for the async world-funnel pipeline: the task + the analysis.

    The analysis is reported as it was *accepted*; the client polls
    ``GET /analyses/{id}`` for the ranked/enriched result once the worker finishes.
    """

    task_id: str
    analysis: AnalysisOut

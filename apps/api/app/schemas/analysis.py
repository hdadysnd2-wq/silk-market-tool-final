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
    #: After Stage 2 the dict also carries ``score_components`` — the per-country
    #: engine scoring components, each ``{value, source, confidence, note}`` —
    #: plus ``score_confidence`` and ``score_model`` (transparent scoring, J1).
    stage2_score: float | None = None
    enrichment: dict | None = None
    #: Deterministic one-line "why this market ranked" (top-5 rows only, J1):
    #: names the two heaviest present scoring components with their real values
    #: and sources. None until Stage 2 has produced score components — a
    #: declared absence, never an invented justification (I1).
    rationale_en: str | None = None
    rationale_ar: str | None = None
    #: Stage-3 per-market deep-dive (competitors, requirements, correlation
    #: threads). None until Stage 3 runs; a declared gap for an unmapped market.
    deepdive: dict | None = None

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
    #: Why a pipeline stage failed (only set when ``status`` is ``failed``) so the
    #: UI can show a terminal state and offer a re-run instead of polling forever.
    failure_reason: str | None = None
    created_at: datetime
    #: Markets screened worldwide in Stage 1 — the real world count behind the
    #: funnel ("screened N → shortlisted M → top 5"). None for older runs.
    total_screened: int | None = None
    #: How many markets the Stage-1 top-20% cut kept for Stage 2 (J1). None for
    #: runs predating the proportional shortlist.
    shortlisted: int | None = None
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

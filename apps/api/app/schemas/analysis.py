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
    #: The world-funnel shortlist ("world screened → top 5"), transit-flagged.
    rankings: list[CountryRankingOut] = []

    model_config = {"from_attributes": True}

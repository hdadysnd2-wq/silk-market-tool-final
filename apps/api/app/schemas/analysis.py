"""API schemas for analysis runs and their world-funnel country rankings."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CountryRankingOut(BaseModel):
    rank: int
    importer_iso3: str
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

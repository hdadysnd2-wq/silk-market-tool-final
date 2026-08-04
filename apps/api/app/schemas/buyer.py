from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ContactOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    title: str | None
    language: str
    verification_status: str

    model_config = {"from_attributes": True}


class BuyerOut(BaseModel):
    id: uuid.UUID
    name: str
    country_iso2: str
    city: str | None
    domain: str | None
    website: str | None
    industry: str | None
    employee_count: int | None
    source: str
    source_confidence: float
    legal_review_required: bool
    #: Lead validity (rule 6 / I8): when the record was last refreshed, the instant
    #: it stops being current (freshness + 90d), and whether it is now stale. A
    #: stale lead must be shown with an explicit warning, never as current data.
    freshness_at: datetime | None = None
    valid_until: datetime | None = None
    is_stale: bool = False

    model_config = {"from_attributes": True}


class BuyerMatchOut(BaseModel):
    buyer: BuyerOut
    market_iso2: str
    relevance_score: int
    score_breakdown: dict | None
    evidence: dict | None
    #: Lawful basis for direct marketing to this lead (I8), recorded at discovery.
    lawful_basis: str | None = None
    basis_note: str | None = None
    contacts: list[ContactOut] = []


class DiscoverRequest(BaseModel):
    markets: list[str]


class CompetitorSnapshotOut(BaseModel):
    hs_code: str
    market_iso2: str
    total_import_usd: float | None
    trend_pct: float | None
    top_exporters: list[dict] | None
    yearly_values: list[dict] | None
    source: str

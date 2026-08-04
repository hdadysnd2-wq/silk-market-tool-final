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
    #: Observed competitor prices from the deepen price layer (I5); None until fetched.
    observed_prices: list[dict] | None = None
    source: str


class CompetitorMarginOut(BaseModel):
    """One competitor's observed price and the exporter's margin against it."""

    competitor: str
    observed_price: float | None  # None = a declared gap (I1)
    currency: str | None
    #: Gross headroom vs the market price ((observed - offer) / observed), a
    #: fraction (0.25 = 25%). None when it cannot be computed honestly (no offer,
    #: currency mismatch, missing price) — never a fabricated margin (I1).
    margin_pct: float | None
    source: str | None
    url: str | None = None
    note: str = ""


class MarginThreadOut(BaseModel):
    """The competitor margin thread: name + observed price + computed margin.

    Derived with ZERO external calls from the factory's own offer price and the
    observed competitor prices already fetched by the deepen price layer — every
    figure is computed or a declared gap (I1), never fabricated.
    """

    hs_code: str | None
    market_iso2: str
    factory_offer: float | None
    factory_currency: str | None
    median_observed_price: float | None
    median_margin_pct: float | None
    competitors: list[CompetitorMarginOut]
    source_line: str
    limits: list[str]

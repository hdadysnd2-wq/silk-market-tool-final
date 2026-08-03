"""Product export-intelligence report — the read-only aggregate that powers the
in-app report view and the downloadable HTML document.

Everything here is assembled from data the platform has already produced
(classification, competitor snapshots, discovered buyers). Building a report has
no side effects: it never calls an external provider or writes to the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ReportFactory(BaseModel):
    name_en: str
    name_ar: str
    sector: str | None
    city: str | None
    website: str | None
    contact_person: str | None
    contact_email: str | None
    contact_phone: str | None


class ReportProduct(BaseModel):
    id: uuid.UUID
    name_en: str
    name_ar: str
    description_en: str | None
    description_ar: str | None
    image_url: str | None
    price_min: float | None
    price_max: float | None
    currency: str
    hs_code: str | None
    hs_description_en: str | None
    hs_description_ar: str | None
    hs_confirmed_by_user: bool
    classification_status: str
    #: Classifier confidence for the confirmed/chosen HS code, if known.
    hs_confidence: float | None


class ReportExporter(BaseModel):
    exporter_iso2: str | None
    exporter_name: str | None
    value_usd: float | None
    share_pct: float | None


class ReportYear(BaseModel):
    year: int
    value_usd: float | None


class ReportSnapshot(BaseModel):
    total_import_usd: float | None
    trend_pct: float | None
    top_exporters: list[ReportExporter]
    yearly_values: list[ReportYear]
    source: str


class ReportContact(BaseModel):
    full_name: str | None
    title: str | None
    email: str
    verification_status: str


class ReportBuyer(BaseModel):
    name: str
    city: str | None
    website: str | None
    industry: str | None
    employee_count: int | None
    source: str
    relevance_score: int
    evidence_summary: str | None
    legal_review_required: bool
    contacts: list[ReportContact]


class ReportMarket(BaseModel):
    iso2: str
    name_en: str
    name_ar: str
    is_gcc: bool
    is_eu: bool
    is_us: bool
    buyer_count: int
    contact_count: int
    #: Competitor snapshot for (hs_code, market); ``None`` if not yet analyzed.
    snapshot: ReportSnapshot | None
    top_buyers: list[ReportBuyer]


class ReportSummary(BaseModel):
    markets_analyzed: int
    total_buyers: int
    total_contacts: int
    verified_contacts: int
    #: Sum of the latest-year import value across analyzed markets, in USD.
    total_import_usd: float | None
    #: ISO2 of the market with the largest current import value, if any.
    top_market_iso2: str | None


class ReportFunnelMarket(BaseModel):
    """One world-funnel market in the report's "world screened → top N" shortlist."""

    rank: int
    importer_iso3: str
    #: Alpha-2 for the competitor/buyer machinery; None for an unmapped market.
    market_iso2: str | None
    year: int | None
    import_usd: float | None  # None = a declared gap (I1), never a fabricated number
    is_transit_hub: bool
    is_mirror: bool
    tags: list[str] | None


class ReportFunnel(BaseModel):
    """The world-market funnel result: the top markets an analysis screened to."""

    #: The confirmed HS6 the world markets were screened for.
    hs_code: str | None
    #: Number of markets in the persisted shortlist (a faithful lower bound on the
    #: total screened; the top slice of these is surfaced as ``top_markets``).
    shortlisted_count: int
    #: The transit-flagged (I9), year-stamped (decision #8) top markets.
    top_markets: list[ReportFunnelMarket]


class ProductReportOut(BaseModel):
    generated_at: datetime
    locale: str
    factory: ReportFactory
    product: ReportProduct
    summary: ReportSummary
    #: "World screened → top N" — the funnel shortlist, or None if no analysis ran.
    funnel: ReportFunnel | None
    markets: list[ReportMarket]

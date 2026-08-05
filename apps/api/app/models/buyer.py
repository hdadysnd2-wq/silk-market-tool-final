"""Normalized buyer companies, their contacts, and product-buyer match scores."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    BUYER_SOURCE_ENUM,
    VERIFICATION_STATUS_ENUM,
    Base,
    BuyerSource,
    TimestampMixin,
    UUIDMixin,
    VerificationStatus,
)


class Buyer(UUIDMixin, TimestampMixin, Base):
    """A potential importer/distributor, deduplicated per (normalized name, country)."""

    __tablename__ = "buyers"
    __table_args__ = (
        UniqueConstraint("normalized_name", "country_iso2", name="normalized_name_country"),
        Index("ix_buyers_country_iso2", "country_iso2"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_iso2: Mapped[str] = mapped_column(
        String(2), ForeignKey("markets.iso2", ondelete="RESTRICT"), nullable=False
    )
    city: Mapped[str | None] = mapped_column(String(120))
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    website: Mapped[str | None] = mapped_column(String(512))
    phone: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(String(512))
    industry: Mapped[str | None] = mapped_column(String(120))
    employee_count: Mapped[int | None] = mapped_column(Integer)

    source: Mapped[BuyerSource] = mapped_column(BUYER_SOURCE_ENUM, nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(64))
    source_confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5, nullable=False)
    #: Raw enrichment payload (size, revenue band, key people, ...).
    firmographics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: When the underlying record was last refreshed from its source.
    freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Google Maps derived rows are isolated in their own tier for legal review.
    legal_review_required: Mapped[bool] = mapped_column(default=False, nullable=False)


class ProductBuyerMatch(UUIDMixin, TimestampMixin, Base):
    """Relevance of one buyer to one product in a given target market."""

    __tablename__ = "product_buyer_matches"
    __table_args__ = (
        UniqueConstraint("product_id", "buyer_id", name="product_buyer"),
        Index(
            "ix_product_buyer_matches_product_score",
            "product_id",
            "relevance_score",
            postgresql_ops={"relevance_score": "DESC"},
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("buyers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    market_iso2: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    relevance_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Per-factor points, surfaced verbatim in the UI so the score is explainable.
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Human-readable evidence, e.g. "imported 42 shipments of HS 3920 in 12 months".
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Lawful basis for direct marketing to this lead (I8 / PDPL Art.25 / GDPR),
    #: recorded per lead at discovery from the evidence that established it —
    #: "prior_import_activity" (the buyer already imports this HS category) or
    #: "directory_listing" (public listing, no import history → needs review).
    lawful_basis: Mapped[str | None] = mapped_column(String(40))
    basis_note: Mapped[str | None] = mapped_column(String(512))
    #: Decision #6 / I8 — the analysis this lead fetch was bound to. Discovery is
    #: only triggered in service of a specific analysis (no bulk pre-fetch); the
    #: stamp makes that binding auditable. SET NULL keeps the match if the
    #: analysis record is later erased; rows predating this column are NULL.
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analyses.id", ondelete="SET NULL"),
        index=True,
    )


class Contact(UUIDMixin, TimestampMixin, Base):
    """A decision-maker at a buyer company, with verification state."""

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("buyer_id", "email", name="buyer_email"),)

    buyer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("buyers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(160))
    title: Mapped[str | None] = mapped_column(String(160))
    language: Mapped[str] = mapped_column(String(2), default="en", nullable=False)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        VERIFICATION_STATUS_ENUM,
        default=VerificationStatus.unverified,
        nullable=False,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(64))
    found_via: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5, nullable=False)

"""HS code reference data, factory products, and classifier feedback."""

from __future__ import annotations

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

#: Dimension of the product embedding stored in pgvector.
EMBEDDING_DIM = 256


class HSCode(TimestampMixin, Base):
    """Reference table covering HS2 / HS4 / HS6 levels."""

    __tablename__ = "hs_codes"

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    parent_code: Mapped[str | None] = mapped_column(String(6), index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)  # 2, 4 or 6
    description_en: Mapped[str] = mapped_column(Text(), nullable=False)
    description_ar: Mapped[str] = mapped_column(Text(), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(64), index=True)


class Product(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "products"

    factory_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("factories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    description_ar: Mapped[str | None] = mapped_column(Text())
    description_en: Mapped[str | None] = mapped_column(Text())
    #: Salient visual attributes from the vision pass ([{name, value}, …]).
    attributes: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    #: Human-visible URL for the image (presigned S3 URL, or a local file:// path
    #: in dev). Display-only — may expire; never used by the worker to fetch bytes.
    image_url: Mapped[str | None] = mapped_column(String(512))
    #: Stable storage key (backend-agnostic). The worker fetches image bytes by
    #: this key through the storage interface, so a multi-container deploy reads
    #: the same object the API wrote — unlike image_url, which was a file:// path
    #: on the API container the worker could not read.
    image_key: Mapped[str | None] = mapped_column(String(512))
    price_min: Mapped[float | None] = mapped_column(Numeric(14, 2))
    price_max: Mapped[float | None] = mapped_column(Numeric(14, 2))
    #: Real factory-declared per-unit production cost, in ``currency``. When set,
    #: the margin thread computes an actual gross margin against it; when null it
    #: falls back to the offer-price estimate (see services/margin.py).
    cost_per_unit: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    hs_code: Mapped[str | None] = mapped_column(
        String(6), ForeignKey("hs_codes.code", ondelete="SET NULL"), index=True
    )
    #: Top-3 HS6 candidates from the classifier: [{code, confidence, rationale}].
    hs_candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    hs_confirmed_by_user: Mapped[bool] = mapped_column(default=False, nullable=False)
    #: True when ``hs_code`` was committed by the engine's strict ``tier="auto"``
    #: gate (owner decision 2026-08-08, ADR-0009) rather than a human. Distinct
    #: from ``hs_confirmed_by_user`` on purpose — provenance is never blurred: a
    #: human confirm/override clears this flag and remains supreme (I2).
    hs_auto_classified: Mapped[bool] = mapped_column(default=False, nullable=False)

    @property
    def hs_ready(self) -> bool:
        """The ONE downstream-gate predicate: a committed HS code, whether
        human-confirmed or strict-auto committed (ADR-0009). Every endpoint or
        task that used to require ``hs_confirmed_by_user`` gates on this instead
        — provenance stays visible on the two flags, but readiness is one
        choke point."""
        return bool(self.hs_code and (self.hs_confirmed_by_user or self.hs_auto_classified))

    classification_status: Mapped[str] = mapped_column(
        String(24), default="pending", nullable=False
    )  # pending | classified | failed
    #: Human-readable reason the intake pipeline failed (set on the terminal
    #: ``failed`` status so the UI can explain, and offer retry / manual entry).
    failure_reason: Mapped[str | None] = mapped_column(String(500))

    #: Deep-research (Top-5) report status — the paid, key-gated engine pipeline
    #: (ADR-0007), DISTINCT from the always-available executive report. None until
    #: first requested, then: pending → ready | gated | failed. ``gated`` is the
    #: fail-closed "deep research pending API key" terminal state (no key) — its
    #: stored docx is a declared-gap document, never fabricated (I1).
    research_status: Mapped[str | None] = mapped_column(String(24))
    #: Storage key of the rendered deep-research docx (``reports/research/{id}.docx``)
    #: once a report (real or declared-gap) has been produced. None until then.
    research_report_key: Mapped[str | None] = mapped_column(String(512))

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class HSCorrection(UUIDMixin, TimestampMixin, Base):
    """Every user override of a suggested HS code, kept to improve prompts."""

    __tablename__ = "hs_corrections"

    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suggested_code: Mapped[str | None] = mapped_column(String(6))
    suggested_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    chosen_code: Mapped[str] = mapped_column(String(6), nullable=False)
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

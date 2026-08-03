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
    image_url: Mapped[str | None] = mapped_column(String(512))
    price_min: Mapped[float | None] = mapped_column(Numeric(14, 2))
    price_max: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    hs_code: Mapped[str | None] = mapped_column(
        String(6), ForeignKey("hs_codes.code", ondelete="SET NULL"), index=True
    )
    #: Top-3 HS6 candidates from the classifier: [{code, confidence, rationale}].
    hs_candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    hs_confirmed_by_user: Mapped[bool] = mapped_column(default=False, nullable=False)
    classification_status: Mapped[str] = mapped_column(
        String(24), default="pending", nullable=False
    )  # pending | classified | failed

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

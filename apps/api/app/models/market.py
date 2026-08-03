"""Target markets and cached competitor snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Market(TimestampMixin, Base):
    __tablename__ = "markets"

    iso2: Mapped[str] = mapped_column(String(2), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    primary_language: Mapped[str] = mapped_column(String(2), default="en", nullable=False)
    is_gcc: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: EU membership drives the GDPR Legitimate Interest Assessment requirement.
    is_eu: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_us: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MarketSnapshot(UUIDMixin, TimestampMixin, Base):
    """Competitor snapshot + market sizing for one (hs_code, market) pair."""

    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("hs_code", "market_iso2", name="hs_code_market"),)

    hs_code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    market_iso2: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    total_import_usd: Mapped[float | None] = mapped_column(Numeric(18, 2))
    trend_pct: Mapped[float | None] = mapped_column(Numeric(6, 2))
    #: [{exporter_iso2, exporter_name, value_usd, share_pct}]
    top_exporters: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    #: [{year, value_usd}]
    yearly_values: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(32), default="comtrade", nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

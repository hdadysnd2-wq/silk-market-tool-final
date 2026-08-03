"""Precomputed world import flows — the funnel's Stage 1 screening table.

Stage 1 of the 3-stage world funnel screens every importer in the world for an
HS6 with ZERO live API calls: one local SQL query over this precomputed table.
``etl/world_trade_sync.py`` refreshes it monthly/quarterly from UN Comtrade bulk
endpoints (pandas + comtradeapicall live in etl/ only — I7).

Provenance and the transit-port guard (I9) are first-class columns:
``is_transit_hub`` flags re-export hubs whose import volumes are inflated by
transshipment (AE, NL, SG, HK, BE, …); ``is_mirror`` flags rows derived from
mirror (partner-reported) data. A failed fetch stores ``import_usd=None`` rather
than a fabricated figure (I1).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class WorldTrade(UUIDMixin, TimestampMixin, Base):
    """One (hs6, importer, year) world-import row, precomputed for Stage 1."""

    __tablename__ = "world_trade"
    __table_args__ = (
        UniqueConstraint("hs6", "importer_iso3", "year", name="uq_world_trade_hs6_importer_year"),
    )

    hs6: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    importer_iso3: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Reported import value / quantity. None (not 0) on a failed fetch (I1).
    import_usd: Mapped[float | None] = mapped_column(Numeric(18, 2))
    import_qty: Mapped[float | None] = mapped_column(Numeric(18, 2))
    #: Year-over-year growth and 3-year CAGR as fractions (0.15 = +15%).
    yoy_growth: Mapped[float | None] = mapped_column(Numeric(8, 4))
    cagr_3y: Mapped[float | None] = mapped_column(Numeric(8, 4))

    #: Transit-port guard (I9): a re-export hub whose imports include re-exports.
    is_transit_hub: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Row derived from mirror (partner-reported) data rather than direct reports.
    is_mirror: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    source: Mapped[str] = mapped_column(String(64), default="UN Comtrade", nullable=False)
    #: When the underlying figure was fetched (data provenance, not row audit).
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

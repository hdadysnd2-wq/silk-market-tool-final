"""Customs / bill-of-lading shipment records — the strongest buy-intent signal."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BUYER_SOURCE_ENUM, Base, BuyerSource, TimestampMixin, UUIDMixin


class Shipment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "shipments"
    __table_args__ = (Index("ix_shipments_hs_dest_date", "hs_code", "dest_iso2", "shipment_date"),)

    buyer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buyers.id", ondelete="SET NULL"), index=True
    )
    #: Consignee name as it appeared in the source record, before normalization.
    raw_consignee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_shipper_name: Mapped[str | None] = mapped_column(String(255))
    hs_code: Mapped[str] = mapped_column(String(6), nullable=False)
    origin_iso2: Mapped[str] = mapped_column(String(2), nullable=False)
    dest_iso2: Mapped[str] = mapped_column(String(2), nullable=False)
    shipment_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_usd: Mapped[float | None] = mapped_column(Numeric(16, 2))
    quantity: Mapped[float | None] = mapped_column(Numeric(16, 3))
    quantity_unit: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[BuyerSource] = mapped_column(
        BUYER_SOURCE_ENUM, default=BuyerSource.customs, nullable=False
    )
    provider_name: Mapped[str | None] = mapped_column(String(64))
    source_confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.9, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True)

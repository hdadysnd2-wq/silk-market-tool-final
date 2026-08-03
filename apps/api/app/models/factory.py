"""Factory (tenant) profile including its sending-domain deliverability state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Factory(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "factories"

    # Bilingual profile — Arabic is the primary locale for factory-facing content.
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    description_ar: Mapped[str | None] = mapped_column(Text())
    description_en: Mapped[str | None] = mapped_column(Text())
    sector: Mapped[str | None] = mapped_column(String(64), index=True)
    city: Mapped[str | None] = mapped_column(String(120))
    country_iso2: Mapped[str] = mapped_column(String(2), default="SA", nullable=False)
    website: Mapped[str | None] = mapped_column(String(255))
    logo_url: Mapped[str | None] = mapped_column(String(512))
    cr_number: Mapped[str | None] = mapped_column(String(64))

    # Sender identity — required in every outbound email (CAN-SPAM / PDPL).
    contact_person: Mapped[str | None] = mapped_column(String(160))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(64))
    postal_address: Mapped[str | None] = mapped_column(Text())

    # Deliverability. Cold email always goes out on the factory's own domain,
    # never the platform root domain.
    sending_domain: Mapped[str | None] = mapped_column(String(255))
    spf_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dkim_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dmarc_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warmup_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warmup_day: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_send_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_counter_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inbox_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sends_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paused_reason: Mapped[str | None] = mapped_column(String(255))

    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @property
    def dns_ready(self) -> bool:
        return self.spf_ok and self.dkim_ok and self.dmarc_ok

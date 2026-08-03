"""Outreach campaigns and their GDPR Legitimate Interest Assessment records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    CAMPAIGN_STATUS_ENUM,
    Base,
    CampaignStatus,
    TimestampMixin,
    UUIDMixin,
)


class Campaign(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    factory_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("factories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The connected mailbox this campaign sends from. Set at creation to the
    #: factory's verified sender account; a verified account is a hard
    #: prerequisite for creating a campaign. ``SET NULL`` keeps the campaign row
    #: if the mailbox is later disconnected (its sends are then blocked).
    sender_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sender_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    market_iso2: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[CampaignStatus] = mapped_column(
        CAMPAIGN_STATUS_ENUM, default=CampaignStatus.draft, nullable=False
    )
    paused_reason: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Set by an internal analyst when preparing a campaign on a factory's behalf.
    prepared_by_staff: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Denormalized counters powering the dashboard.
    total_emails: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opened_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replied_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bounced_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    complained_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: Self-reported outcome, used for the "meetings / RFQs generated" metric.
    reported_meetings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reported_rfqs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    @property
    def bounce_rate(self) -> float:
        return self.bounced_count / self.sent_count if self.sent_count else 0.0

    @property
    def complaint_rate(self) -> float:
        return self.complained_count / self.sent_count if self.sent_count else 0.0

    @property
    def reply_rate(self) -> float:
        return self.replied_count / self.sent_count if self.sent_count else 0.0


class LIARecord(UUIDMixin, TimestampMixin, Base):
    """Legitimate Interest Assessment — required before emailing any EU market."""

    __tablename__ = "lia_records"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    purpose_text: Mapped[str] = mapped_column(Text(), nullable=False)
    necessity_text: Mapped[str] = mapped_column(Text(), nullable=False)
    balancing_test_text: Mapped[str] = mapped_column(Text(), nullable=False)
    data_sources: Mapped[str | None] = mapped_column(Text())
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

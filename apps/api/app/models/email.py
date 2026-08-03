"""Outbound emails.

The approval gate is a hard product requirement, so it is expressed three times:
at the API layer, again inside the send worker, and finally as the CHECK
constraint declared here — no code path, present or future, can persist a
sent-family status without a recorded approver.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    EMAIL_STATUS_ENUM,
    SENT_FAMILY_STATUSES,
    Base,
    EmailStatus,
    TimestampMixin,
    UUIDMixin,
)

_SENT_FAMILY_SQL = ", ".join(f"'{s.value}'" for s in SENT_FAMILY_STATUSES)

#: A message may only carry a sent-family status if a human approved it.
APPROVAL_CHECK_SQL = (
    f"status NOT IN ({_SENT_FAMILY_SQL}) OR (approved_at IS NOT NULL AND approved_by IS NOT NULL)"
)


class Email(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "emails"
    __table_args__ = (
        CheckConstraint(APPROVAL_CHECK_SQL, name="sent_requires_approval"),
        Index("ix_emails_campaign_status", "campaign_id", "status"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buyers.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[EmailStatus] = mapped_column(
        EMAIL_STATUS_ENUM, default=EmailStatus.draft, nullable=False
    )
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    body_text: Mapped[str] = mapped_column(Text(), nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text())
    language: Mapped[str] = mapped_column(String(2), default="en", nullable=False)

    is_followup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    followup_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parent_email_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("emails.id", ondelete="SET NULL")
    )

    #: Token behind the one-click unsubscribe link embedded in every message.
    unsubscribe_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # Approval provenance — written only by services.approval.transition().
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_note: Mapped[str | None] = mapped_column(Text())
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounce_type: Mapped[str | None] = mapped_column(String(32))
    blocked_reason: Mapped[str | None] = mapped_column(String(255))

    provider_name: Mapped[str | None] = mapped_column(String(64))
    provider_message_id: Mapped[str | None] = mapped_column(String(128), index=True)

    @property
    def is_approved(self) -> bool:
        return self.approved_at is not None and self.approved_by is not None

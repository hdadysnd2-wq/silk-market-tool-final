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

#: A message may only carry a sent-family status if a human approved it. The gate
#: keys on ``approved_at`` (the timestamp of the human act), NOT ``approved_by``:
#: the approver's user row may later be erased (PDPL/offboarding), which sets
#: ``approved_by`` NULL via ``ON DELETE SET NULL``. Who approved is preserved
#: durably in ``approved_by_label`` (a snapshot), so the record stays complete
#: while user erasure is no longer blocked by this constraint.
APPROVAL_CHECK_SQL = f"status NOT IN ({_SENT_FAMILY_SQL}) OR approved_at IS NOT NULL"


class Email(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "emails"
    __table_args__ = (
        CheckConstraint(APPROVAL_CHECK_SQL, name="sent_requires_approval"),
        Index("ix_emails_campaign_status", "campaign_id", "status"),
        # The hourly follow-up sweep scans by (status, sent_at) and anti-joins
        # on parent_email_id (migration 0019).
        Index("ix_emails_status_sent_at", "status", "sent_at"),
        Index("ix_emails_parent_email_id", "parent_email_id"),
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
    #: Durable snapshot of who approved (email/label), captured at approval time so
    #: the trail survives erasure of the approver's user row (approved_by → NULL).
    approved_by_label: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_note: Mapped[str | None] = mapped_column(Text())
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When the send worker claimed this row for egress (status → ``sending``).
    #: A stale claim is how the reaper finds sends interrupted mid-flight.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

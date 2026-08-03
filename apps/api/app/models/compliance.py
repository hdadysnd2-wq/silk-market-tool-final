"""Suppression ledger and the append-only audit log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    SUPPRESSION_REASON_ENUM,
    Base,
    SuppressionReason,
    TimestampMixin,
    UUIDMixin,
    utcnow,
)


class SuppressionEntry(UUIDMixin, TimestampMixin, Base):
    """A globally suppressed address.

    Scope is deliberately global rather than per-factory: an unsubscribe from one
    campaign silences every campaign on the platform, which is the strictest
    reading of PDPL / GDPR / CAN-SPAM and the safest default.
    """

    __tablename__ = "suppression_list"

    email_norm: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    reason: Mapped[SuppressionReason] = mapped_column(SUPPRESSION_REASON_ENUM, nullable=False)
    source_email_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("emails.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text())


class AuditLog(TimestampMixin, Base):
    """Append-only record of every consequential action.

    Immutability is enforced by a database trigger created in migration 0001;
    UPDATE and DELETE on this table raise.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_label: Mapped[str | None] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    factory_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("factories.id", ondelete="SET NULL"), index=True
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

"""Per-factory connected mailboxes (multi-tenant OAuth email sending).

Each factory connects its own Gmail / Microsoft mailbox via OAuth; the platform
then sends on that account's behalf through the provider's API. OAuth tokens are
stored **encrypted** (see ``app.crypto``) — the ``*_encrypted`` columns never hold
plaintext. Per-account send governance (daily counter + warm-up ramp) lives on
this row and is enforced in the send worker, not the UI.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    SENDER_PROVIDER_TYPE_ENUM,
    SENDER_VERIFICATION_STATUS_ENUM,
    Base,
    SenderProviderType,
    SenderVerificationStatus,
    TimestampMixin,
    UUIDMixin,
)


class SenderAccount(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sender_accounts"
    __table_args__ = (
        # A factory connects a given mailbox address once per provider.
        UniqueConstraint("factory_id", "email", "provider_type", name="factory_email_provider"),
    )

    factory_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("factories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_type: Mapped[SenderProviderType] = mapped_column(
        SENDER_PROVIDER_TYPE_ENUM, nullable=False
    )
    #: The provider's stable account id (Google ``sub`` / Graph ``id``).
    provider_account_id: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(160))

    # OAuth secrets — ENCRYPTED AT REST. Never store or log the plaintext.
    access_token_encrypted: Mapped[str | None] = mapped_column(Text())
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text())
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Space-separated scopes actually granted (audit / narrowest-scope checks).
    scopes: Mapped[str | None] = mapped_column(Text())

    verification_status: Mapped[SenderVerificationStatus] = mapped_column(
        SENDER_VERIFICATION_STATUS_ENUM,
        default=SenderVerificationStatus.pending,
        nullable=False,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Human-readable reason set when the account drops to ``needs_reauth``.
    reauth_reason: Mapped[str | None] = mapped_column(String(255))

    # Per-account send governance (enforced in the worker before every send).
    daily_send_limit: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    daily_sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_counter_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Warm-up stage index (1-based); maps to a daily cap that ramps on a schedule.
    warmup_stage: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    warmup_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Last time the reply-detection beat polled this mailbox.
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_verified(self) -> bool:
        return self.verification_status == SenderVerificationStatus.verified

    @property
    def needs_reauth(self) -> bool:
        return self.verification_status == SenderVerificationStatus.needs_reauth


class Notification(UUIDMixin, TimestampMixin, Base):
    """A user-facing alert for a factory (mailbox reauth, replies received, …).

    Deliberately lightweight: ``kind`` is a free string (like ``AuditLog.action``)
    so new event types need no migration. Scoped to a factory for tenant isolation.
    """

    __tablename__ = "notifications"

    factory_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("factories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text())
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

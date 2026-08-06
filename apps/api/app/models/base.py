"""Declarative base, shared column helpers, and enum definitions."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class UserRole(str, enum.Enum):
    factory_user = "factory_user"
    admin = "admin"
    analyst = "analyst"


class EmailStatus(str, enum.Enum):
    """Lifecycle of a single outbound email.

    Only ``draft`` is ever created directly. Everything downstream flows through
    ``services.approval.transition``.
    """

    draft = "draft"
    approved = "approved"
    rejected = "rejected"
    queued = "queued"
    #: Claimed for egress: the row was committed to this state BEFORE the provider
    #: call, so a worker crash / broker redelivery finds it here (not ``queued``)
    #: and refuses to re-send. A reaper resolves rows stuck here.
    sending = "sending"
    sent = "sent"
    opened = "opened"
    replied = "replied"
    bounced = "bounced"
    complained = "complained"
    blocked_suppressed = "blocked_suppressed"
    cancelled = "cancelled"


#: Statuses that mean "this message left the building" — reaching any of them
#: requires a recorded human approval, enforced by a DB CHECK constraint.
#: ``sending`` is included: it is the pre-egress claim and only ever follows
#: ``queued``, so it too must carry a recorded approver.
SENT_FAMILY_STATUSES = (
    EmailStatus.queued,
    EmailStatus.sending,
    EmailStatus.sent,
    EmailStatus.opened,
    EmailStatus.replied,
    EmailStatus.bounced,
    EmailStatus.complained,
)


class VerificationStatus(str, enum.Enum):
    unverified = "unverified"
    valid = "valid"
    risky = "risky"
    invalid = "invalid"


class BuyerSource(str, enum.Enum):
    customs = "customs"
    comtrade = "comtrade"
    enrichment = "enrichment"
    maps = "maps"
    manual = "manual"


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    auto_paused = "auto_paused"
    completed = "completed"


class SuppressionReason(str, enum.Enum):
    unsubscribe = "unsubscribe"
    bounce = "bounce"
    complaint = "complaint"
    manual = "manual"
    legal = "legal"


class SenderProviderType(str, enum.Enum):
    """Which mailbox API a connected sender account sends through."""

    gmail = "gmail"
    microsoft = "microsoft"
    mock = "mock"


class SenderVerificationStatus(str, enum.Enum):
    """Lifecycle of a factory's connected mailbox.

    Only ``verified`` accounts may send. ``needs_reauth`` is entered when a
    refresh token is revoked/expired — sending is halted and the factory must
    reconnect.
    """

    pending = "pending"
    verified = "verified"
    needs_reauth = "needs_reauth"
    disabled = "disabled"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Native Postgres enum storing the *value* (not the Python member name).

    ``create_type=False`` keeps SQLAlchemy from emitting a duplicate ``CREATE TYPE``
    when the same enum backs more than one column; the migration owns creation.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        create_type=False,
    )


# Shared type instances — reuse these so a type used by several tables is only
# defined once.
USER_ROLE_ENUM = pg_enum(UserRole, "user_role")
EMAIL_STATUS_ENUM = pg_enum(EmailStatus, "email_status")
VERIFICATION_STATUS_ENUM = pg_enum(VerificationStatus, "verification_status")
BUYER_SOURCE_ENUM = pg_enum(BuyerSource, "buyer_source")
CAMPAIGN_STATUS_ENUM = pg_enum(CampaignStatus, "campaign_status")
SUPPRESSION_REASON_ENUM = pg_enum(SuppressionReason, "suppression_reason")
SENDER_PROVIDER_TYPE_ENUM = pg_enum(SenderProviderType, "sender_provider_type")
SENDER_VERIFICATION_STATUS_ENUM = pg_enum(SenderVerificationStatus, "sender_verification_status")

ALL_ENUMS = (
    USER_ROLE_ENUM,
    EMAIL_STATUS_ENUM,
    VERIFICATION_STATUS_ENUM,
    BUYER_SOURCE_ENUM,
    CAMPAIGN_STATUS_ENUM,
    SUPPRESSION_REASON_ENUM,
    SENDER_PROVIDER_TYPE_ENUM,
    SENDER_VERIFICATION_STATUS_ENUM,
)

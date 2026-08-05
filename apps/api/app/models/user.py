"""Platform users: factory staff, internal analysts, and admins."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import USER_ROLE_ENUM, Base, TimestampMixin, UserRole, UUIDMixin


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(160))
    role: Mapped[UserRole] = mapped_column(
        USER_ROLE_ENUM, default=UserRole.factory_user, nullable=False
    )
    # NULL for admin/analyst accounts, which are not scoped to one tenant.
    factory_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("factories.id", ondelete="CASCADE"), index=True
    )
    locale: Mapped[str] = mapped_column(String(5), default="ar", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # OTP second factor — codes are hashed at rest and single-use.
    otp_code_hash: Mapped[str | None] = mapped_column(String(255))
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Wrong-code attempts against the current OTP; reset on issue/success. Once it
    # reaches otp_max_attempts the code is locked (online brute-force cap).
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""Shared user-creation service.

Every path that mints a ``User`` row (admin console, production bootstrap)
must build it here so a new column or invariant lands in one place, and every
path that stores or looks up an email must agree on ``normalize_email``.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import User, UserRole
from app.services import audit


def normalize_email(email: str) -> str:
    """The canonical stored/lookup form of an email address."""
    return email.lower().strip()


def create_user(
    db: Session,
    *,
    email: str,
    full_name: str | None,
    role: UserRole,
    factory_id: uuid.UUID | None,
    locale: str,
    password_hash: str,
    actor: User | None = None,
) -> User:
    """Create an active user and its ``user.created`` audit row. Caller commits."""
    user = User(
        email=email,
        full_name=full_name,
        role=role,
        factory_id=factory_id,
        locale=locale,
        password_hash=password_hash,
        is_active=True,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        payload={"email": email, "role": role.value},
    )
    return user

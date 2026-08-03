"""Append-only audit logging.

Every consequential action (approve, reject, queue, send, suppress, act-on-behalf)
records one row here. The table's DB trigger makes the trail tamper-evident;
this service is the only sanctioned way to write to it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    actor: User | None = None,
    actor_label: str | None = None,
    factory_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """Insert an audit row. Caller controls the transaction/commit."""
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        actor_user_id=actor.id if actor else None,
        actor_label=actor_label or (actor.email if actor else "system"),
        factory_id=factory_id or (actor.factory_id if actor else None),
        payload=payload,
    )
    db.add(entry)
    db.flush()
    return entry

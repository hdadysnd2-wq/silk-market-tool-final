"""Factory-facing notifications.

A thin ledger of alerts a factory should see in the app — a mailbox needing
reconnection, a buyer reply that stopped a sequence, and so on. Kept separate
from the immutable ``audit_log`` (which is the compliance record); notifications
are user-facing and mutable (they can be marked read).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Notification, utcnow

log = get_logger(__name__)


def notify(
    db: Session,
    *,
    factory_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None = None,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> Notification:
    """Create a notification for a factory. Caller controls the transaction."""
    note = Notification(
        factory_id=factory_id,
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
    )
    db.add(note)
    db.flush()
    log.info("notification_created", factory_id=str(factory_id), kind=kind)
    return note


def list_for_factory(
    db: Session, factory_id: uuid.UUID, *, unread_only: bool = False, limit: int = 50
) -> list[Notification]:
    query = select(Notification).where(Notification.factory_id == factory_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    query = query.order_by(Notification.created_at.desc()).limit(limit)
    return list(db.scalars(query).all())


def mark_read(db: Session, note: Notification) -> Notification:
    if note.read_at is None:
        note.read_at = utcnow()
        db.flush()
    return note

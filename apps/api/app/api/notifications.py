"""Factory-facing notifications (mailbox reauth, replies, …)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbDep, resolve_factory
from app.models import Notification
from app.schemas.sender import NotificationOut
from app.security import CurrentUser
from app.services import notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    db: DbDep, user: CurrentUser, unread_only: bool = False
) -> list[NotificationOut]:
    factory = resolve_factory(db, user)
    rows = notifications.list_for_factory(db, factory.id, unread_only=unread_only)
    return [NotificationOut.model_validate(n) for n in rows]


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: uuid.UUID, db: DbDep, user: CurrentUser) -> NotificationOut:
    factory = resolve_factory(db, user)
    note = db.get(Notification, notification_id)
    if note is None or note.factory_id != factory.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notifications.mark_read(db, note)
    db.commit()
    return NotificationOut.model_validate(note)

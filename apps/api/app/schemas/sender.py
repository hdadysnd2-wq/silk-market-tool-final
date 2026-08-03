from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SenderAccountOut(BaseModel):
    """A connected mailbox. Deliberately excludes every token field."""

    id: uuid.UUID
    email: str
    provider_type: str
    display_name: str | None
    verification_status: str
    reauth_reason: str | None
    scopes: str | None
    daily_send_limit: int
    daily_sent_count: int
    warmup_stage: int
    verified_at: datetime | None
    last_polled_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectResponse(BaseModel):
    #: The provider consent URL the browser should be redirected to.
    authorization_url: str


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    entity_type: str | None
    entity_id: str | None
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}

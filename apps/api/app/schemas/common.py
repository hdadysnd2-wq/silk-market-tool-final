from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class FactoryOut(BaseModel):
    id: uuid.UUID
    name_ar: str
    name_en: str
    description_ar: str | None = None
    description_en: str | None = None
    sector: str | None = None
    city: str | None = None
    website: str | None = None
    contact_person: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    postal_address: str | None = None
    sending_domain: str | None = None
    spf_ok: bool
    dkim_ok: bool
    dmarc_ok: bool
    warmup_day: int
    daily_send_count: int
    sends_paused: bool
    onboarding_completed: bool

    model_config = {"from_attributes": True}


class FactoryUpdate(BaseModel):
    name_ar: str | None = None
    name_en: str | None = None
    description_ar: str | None = None
    description_en: str | None = None
    sector: str | None = None
    city: str | None = None
    website: str | None = None
    contact_person: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    postal_address: str | None = None
    sending_domain: str | None = None
    onboarding_completed: bool | None = None


class DeliverabilityUpdate(BaseModel):
    sending_domain: str | None = None
    spf_ok: bool | None = None
    dkim_ok: bool | None = None
    dmarc_ok: bool | None = None
    inbox_count: int | None = None
    start_warmup: bool | None = None


class MarketOut(BaseModel):
    iso2: str
    name_en: str
    name_ar: str
    region: str | None
    primary_language: str
    is_gcc: bool
    is_eu: bool
    is_us: bool

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    detail: str


class ErasureRequest(BaseModel):
    email: str


class AuditEntryOut(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: str | None
    actor_label: str | None
    payload: dict | None
    occurred_at: datetime

    model_config = {"from_attributes": True}

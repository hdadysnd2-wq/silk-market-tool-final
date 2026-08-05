from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.models import UserRole


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
    # NOTE: spf_ok/dkim_ok/dmarc_ok are deliberately NOT here. Authentication
    # status is not tenant-attestable — it is set only by the server-side DNS
    # check (POST /factory/deliverability/check). See services/dns_check.py.
    sending_domain: str | None = None
    inbox_count: int | None = None
    start_warmup: bool | None = None


class DnsCheckOut(BaseModel):
    """Result of a deliverability DNS check, alongside the refreshed factory."""

    spf_ok: bool
    dkim_ok: bool
    dmarc_ok: bool
    notes: dict[str, str]


class UserAdminOut(BaseModel):
    """A user as the admin console sees it — never includes any secret."""

    id: uuid.UUID
    # Plain str on output: the address was validated on input, and re-validating
    # here would reject reserved TLDs used by seeded/test accounts (e.g. .test).
    email: str
    full_name: str | None
    role: str
    factory_id: uuid.UUID | None
    locale: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreateRequest(BaseModel):
    # No password: the account is created with an unusable credential and the
    # user establishes access via the OTP/reset flow. Never accept or return one.
    email: EmailStr
    full_name: str | None = None
    role: UserRole
    factory_id: uuid.UUID | None = None
    locale: str = "ar"


class UserUpdateRequest(BaseModel):
    full_name: str | None = None
    locale: str | None = None
    role: UserRole | None = None
    factory_id: uuid.UUID | None = None


class AdminOverviewOut(BaseModel):
    """Cross-tenant snapshot for the staff console (aggregated over all factories)."""

    factories: int
    active_campaigns: int
    pending_approvals: int
    total_sent: int
    bounce_rate: float
    complaint_rate: float


class CampaignAdminOut(BaseModel):
    """A campaign as the cross-tenant staff console sees it."""

    id: uuid.UUID
    name: str
    factory_id: uuid.UUID
    factory_name_en: str
    factory_name_ar: str
    market_iso2: str
    status: str
    paused_reason: str | None
    prepared_by_staff: bool
    total_emails: int
    sent_count: int
    opened_count: int
    replied_count: int
    bounced_count: int
    complained_count: int
    pending_approvals: int
    created_at: datetime


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

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    product_id: uuid.UUID
    market_iso2: str = Field(min_length=2, max_length=2)
    name: str = Field(min_length=1, max_length=255)


class CampaignOut(BaseModel):
    id: uuid.UUID
    factory_id: uuid.UUID
    product_id: uuid.UUID
    sender_account_id: uuid.UUID | None
    market_iso2: str
    name: str
    status: str
    paused_reason: str | None
    total_emails: int
    sent_count: int
    opened_count: int
    replied_count: int
    bounced_count: int
    complained_count: int
    reported_meetings: int
    reported_rfqs: int
    created_at: datetime

    # Computed for the approval UI (not stored on the row): whether this
    # campaign's market is in the EU — so a Legitimate Interest Assessment is
    # required before any send (I8) — and whether one has been recorded. The
    # router populates them; they default False when the object is validated
    # directly.
    market_is_eu: bool = False
    lia_recorded: bool = False

    model_config = {"from_attributes": True}


class EmailOut(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: uuid.UUID
    buyer_id: uuid.UUID
    status: str
    subject: str
    body_text: str
    body_html: str | None
    language: str
    is_followup: bool
    approved_at: datetime | None
    sent_at: datetime | None
    opened_at: datetime | None
    replied_at: datetime | None
    blocked_reason: str | None

    model_config = {"from_attributes": True}


class EmailEditRequest(BaseModel):
    subject: str | None = None
    body_text: str | None = None


class RejectRequest(BaseModel):
    note: str | None = None


class LIACreateRequest(BaseModel):
    purpose_text: str
    necessity_text: str
    balancing_test_text: str
    data_sources: str | None = None


class OutcomeReportRequest(BaseModel):
    reported_meetings: int | None = None
    reported_rfqs: int | None = None


class WebhookEvent(BaseModel):
    event: str
    message_id: str
    bounce_type: str | None = None


class DashboardStats(BaseModel):
    campaigns: int
    total_sent: int
    total_opened: int
    total_replied: int
    total_bounced: int
    open_rate: float
    reply_rate: float
    bounce_rate: float
    pending_approvals: int

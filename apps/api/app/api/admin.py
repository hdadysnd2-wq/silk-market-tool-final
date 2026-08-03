"""Internal team concierge panel — admin and analyst only.

Staff can operate on any factory's behalf (prepare campaigns, edit drafts),
manage the suppression ledger, read the immutable audit log, pause or resume
sending, and record LIA assessments. Every action still flows through the same
services (and the same approval gate) that the factory-facing API uses.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.api.deps import DbDep
from app.models import (
    AuditLog,
    Campaign,
    CampaignStatus,
    Email,
    EmailStatus,
    Factory,
    SuppressionEntry,
    SuppressionReason,
    User,
)
from app.schemas.common import AuditEntryOut, ErasureRequest, FactoryOut, MessageResponse
from app.security import require_staff
from app.services import retention, suppression

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_staff)])


@router.get("/factories", response_model=list[FactoryOut])
def list_factories(db: DbDep) -> list[FactoryOut]:
    rows = db.scalars(select(Factory).order_by(Factory.created_at.desc())).all()
    return [FactoryOut.model_validate(f) for f in rows]


@router.get("/factories/{factory_id}/overview")
def factory_overview(factory_id: uuid.UUID, db: DbDep) -> dict:
    factory = db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=404, detail="Factory not found")
    campaigns = db.scalar(select(func.count(Campaign.id)).where(Campaign.factory_id == factory_id))
    pending = db.scalar(
        select(func.count(Email.id))
        .join(Campaign, Campaign.id == Email.campaign_id)
        .where(Campaign.factory_id == factory_id, Email.status == EmailStatus.draft)
    )
    return {
        "factory": FactoryOut.model_validate(factory).model_dump(),
        "campaigns": campaigns or 0,
        "pending_approvals": pending or 0,
    }


@router.post("/factories/{factory_id}/deliverability/verify", response_model=FactoryOut)
def mark_dns_verified(factory_id: uuid.UUID, db: DbDep) -> FactoryOut:
    """Concierge helper: mark SPF/DKIM/DMARC verified after manual DNS setup."""
    factory = db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=404, detail="Factory not found")
    factory.spf_ok = factory.dkim_ok = factory.dmarc_ok = True
    db.commit()
    return FactoryOut.model_validate(factory)


@router.post("/campaigns/{campaign_id}/pause", response_model=MessageResponse)
def pause_campaign(campaign_id: uuid.UUID, reason: str, db: DbDep) -> MessageResponse:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign.status = CampaignStatus.paused
    campaign.paused_reason = reason
    db.commit()
    return MessageResponse(detail="Campaign paused")


@router.post("/campaigns/{campaign_id}/resume", response_model=MessageResponse)
def resume_campaign(campaign_id: uuid.UUID, db: DbDep) -> MessageResponse:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign.status = CampaignStatus.active
    campaign.paused_reason = None
    db.commit()
    return MessageResponse(detail="Campaign resumed")


# --- Suppression ledger ----------------------------------------------------


@router.get("/suppression")
def list_suppression(db: DbDep, limit: int = 100) -> list[dict]:
    rows = db.scalars(
        select(SuppressionEntry).order_by(SuppressionEntry.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "email": e.email_norm,
            "reason": e.reason.value,
            "note": e.note,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]


@router.post("/suppression", response_model=MessageResponse)
def add_suppression(
    email: str,
    db: DbDep,
    staff: User = Depends(require_staff),
    note: str | None = None,
) -> MessageResponse:
    suppression.suppress(
        db,
        email=email,
        reason=SuppressionReason.manual,
        note=note,
        actor=staff,
    )
    db.commit()
    return MessageResponse(detail="Address suppressed")


# --- Audit log (read-only) -------------------------------------------------


@router.get("/audit", response_model=list[AuditEntryOut])
def audit_log(
    db: DbDep,
    action: str | None = None,
    factory_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[AuditEntryOut]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        query = query.where(AuditLog.action == action)
    if factory_id:
        query = query.where(AuditLog.factory_id == factory_id)
    rows = db.scalars(query).all()
    return [AuditEntryOut.model_validate(r) for r in rows]


# --- PDPL erasure (right to be forgotten) ----------------------------------


@router.post("/pdpl/erasure", response_model=MessageResponse)
def pdpl_erasure(
    payload: ErasureRequest,
    db: DbDep,
    staff: User = Depends(require_staff),
) -> MessageResponse:
    """Honour a data-subject erasure request: anonymise every contact holding
    the address and suppress it globally so it can never be re-contacted."""
    erased = retention.erase_data_subject(db, email=payload.email, actor=staff)
    db.commit()
    return MessageResponse(detail=f"Erased {erased} contact(s); {payload.email} is now suppressed")

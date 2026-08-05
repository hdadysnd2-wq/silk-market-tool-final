"""Internal team concierge panel — admin and analyst only.

Staff can operate on any factory's behalf (prepare campaigns, edit drafts),
manage the suppression ledger, read the immutable audit log, pause or resume
sending, and record LIA assessments. Every action still flows through the same
services (and the same approval gate) that the factory-facing API uses.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
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
    UserRole,
)
from app.schemas.common import (
    AdminOverviewOut,
    AuditEntryOut,
    CampaignAdminOut,
    ErasureRequest,
    FactoryOut,
    MessageResponse,
    UserAdminOut,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.security import hash_password, require_roles, require_staff
from app.services import audit, auth_service, retention, suppression

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_staff)])

# User mutations are admin-only; analysts may read (list) but not change users.
require_admin = require_roles(UserRole.admin)
_STAFF_ROLES = (UserRole.admin, UserRole.analyst)


@router.get("/overview", response_model=AdminOverviewOut)
def overview(db: DbDep) -> AdminOverviewOut:
    """Cross-tenant health snapshot for the staff console.

    Rates are derived from the same per-campaign counters the factory dashboard
    sums (sent/bounced/complained), so admin and tenant figures reconcile.
    """
    factories = db.scalar(select(func.count(Factory.id))) or 0
    active_campaigns = (
        db.scalar(select(func.count(Campaign.id)).where(Campaign.status == CampaignStatus.active))
        or 0
    )
    pending_approvals = (
        db.scalar(select(func.count(Email.id)).where(Email.status == EmailStatus.draft)) or 0
    )
    sent, bounced, complained = db.execute(
        select(
            func.coalesce(func.sum(Campaign.sent_count), 0),
            func.coalesce(func.sum(Campaign.bounced_count), 0),
            func.coalesce(func.sum(Campaign.complained_count), 0),
        )
    ).one()
    sent = int(sent)
    return AdminOverviewOut(
        factories=int(factories),
        active_campaigns=int(active_campaigns),
        pending_approvals=int(pending_approvals),
        total_sent=sent,
        bounce_rate=round(int(bounced) / sent, 4) if sent else 0.0,
        complaint_rate=round(int(complained) / sent, 4) if sent else 0.0,
    )


# --- User management (admin-only mutations; staff may list) ---------------


def _factory_for_role(db: DbDep, role: UserRole, factory_id: uuid.UUID | None) -> uuid.UUID | None:
    """Enforce role↔factory consistency: staff are never tenant-scoped (NULL);
    factory users require an existing factory."""
    if role in _STAFF_ROLES:
        return None
    if factory_id is None:
        raise HTTPException(status_code=400, detail="Factory users require a factory_id")
    if db.get(Factory, factory_id) is None:
        raise HTTPException(status_code=404, detail="Factory not found")
    return factory_id


def _active_admin_count(db: DbDep, *, exclude_id: uuid.UUID | None = None) -> int:
    query = select(func.count(User.id)).where(User.role == UserRole.admin, User.is_active.is_(True))
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return db.scalar(query) or 0


@router.get("/users", response_model=list[UserAdminOut])
def list_users(
    db: DbDep,
    role: UserRole | None = None,
    factory_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 100,
) -> list[UserAdminOut]:
    query = select(User).order_by(User.created_at.desc()).limit(limit)
    if role is not None:
        query = query.where(User.role == role)
    if factory_id is not None:
        query = query.where(User.factory_id == factory_id)
    if q:
        pattern = f"%{q.lower()}%"
        query = query.where(
            func.lower(User.email).like(pattern)
            | func.lower(func.coalesce(User.full_name, "")).like(pattern)
        )
    return [UserAdminOut.model_validate(u) for u in db.scalars(query).all()]


@router.post("/users", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    db: DbDep,
    actor: User = Depends(require_admin),
) -> UserAdminOut:
    email = payload.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="Email already in use")
    factory_id = _factory_for_role(db, payload.role, payload.factory_id)
    user = User(
        email=email,
        full_name=payload.full_name,
        role=payload.role,
        factory_id=factory_id,
        locale=payload.locale,
        # Unusable credential — the user gains access via the OTP/reset flow.
        # No password is ever accepted from or returned to the caller.
        password_hash=hash_password(secrets.token_urlsafe(32)),
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
        payload={"email": email, "role": payload.role.value},
    )
    db.commit()
    return UserAdminOut.model_validate(user)


@router.put("/users/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    db: DbDep,
    actor: User = Depends(require_admin),
) -> UserAdminOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    data = payload.model_dump(exclude_unset=True)

    if "role" in data or "factory_id" in data:
        new_role = data.get("role", user.role)
        new_factory = data.get("factory_id", user.factory_id)
        demoting_admin = user.role == UserRole.admin and new_role != UserRole.admin
        if demoting_admin and user.id == actor.id:
            raise HTTPException(status_code=400, detail="You cannot change your own admin role")
        if demoting_admin and user.is_active and _active_admin_count(db, exclude_id=user.id) == 0:
            raise HTTPException(status_code=400, detail="At least one active admin must remain")
        user.factory_id = _factory_for_role(db, new_role, new_factory)
        user.role = new_role
    if "full_name" in data:
        user.full_name = data["full_name"]
    if "locale" in data:
        user.locale = data["locale"]

    audit.record(
        db,
        action="user.updated",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        payload={"role": user.role.value},
    )
    db.commit()
    return UserAdminOut.model_validate(user)


@router.post("/users/{user_id}/deactivate", response_model=UserAdminOut)
def deactivate_user(
    user_id: uuid.UUID,
    db: DbDep,
    actor: User = Depends(require_admin),
) -> UserAdminOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    if (
        user.role == UserRole.admin
        and user.is_active
        and _active_admin_count(db, exclude_id=user.id) == 0
    ):
        raise HTTPException(status_code=400, detail="At least one active admin must remain")
    user.is_active = False
    audit.record(
        db,
        action="user.deactivated",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
    )
    db.commit()
    return UserAdminOut.model_validate(user)


@router.post("/users/{user_id}/activate", response_model=UserAdminOut)
def activate_user(
    user_id: uuid.UUID,
    db: DbDep,
    actor: User = Depends(require_admin),
) -> UserAdminOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    audit.record(
        db,
        action="user.activated",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
    )
    db.commit()
    return UserAdminOut.model_validate(user)


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_user_password(
    user_id: uuid.UUID,
    db: DbDep,
    actor: User = Depends(require_admin),
) -> Response:
    """Trigger the OTP/reset flow for a user. Never returns (or logs) the code."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    auth_service.issue_otp(db, user)  # code is stored hashed; never surfaced here
    audit.record(
        db,
        action="user.password_reset",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
def mark_dns_verified(
    factory_id: uuid.UUID, db: DbDep, staff: User = Depends(require_staff)
) -> FactoryOut:
    """Concierge helper: mark SPF/DKIM/DMARC verified after manual DNS setup."""
    factory = db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=404, detail="Factory not found")
    factory.spf_ok = factory.dkim_ok = factory.dmarc_ok = True
    audit.record(
        db,
        action="factory.dns_verified_by_staff",
        entity_type="factory",
        entity_id=factory.id,
        actor=staff,
        factory_id=factory.id,
    )
    db.commit()
    return FactoryOut.model_validate(factory)


@router.post("/factories/{factory_id}/pause", response_model=FactoryOut)
def pause_factory(
    factory_id: uuid.UUID, reason: str, db: DbDep, staff: User = Depends(require_staff)
) -> FactoryOut:
    """Halt all sending for a tenant (concierge action). Audited."""
    factory = db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=404, detail="Factory not found")
    factory.sends_paused = True
    factory.paused_reason = reason
    audit.record(
        db,
        action="factory.paused",
        entity_type="factory",
        entity_id=factory.id,
        actor=staff,
        factory_id=factory.id,
        payload={"reason": reason},
    )
    db.commit()
    return FactoryOut.model_validate(factory)


@router.post("/factories/{factory_id}/resume", response_model=FactoryOut)
def resume_factory(
    factory_id: uuid.UUID, db: DbDep, staff: User = Depends(require_staff)
) -> FactoryOut:
    factory = db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=404, detail="Factory not found")
    factory.sends_paused = False
    factory.paused_reason = None
    audit.record(
        db,
        action="factory.resumed",
        entity_type="factory",
        entity_id=factory.id,
        actor=staff,
        factory_id=factory.id,
    )
    db.commit()
    return FactoryOut.model_validate(factory)


@router.get("/campaigns", response_model=list[CampaignAdminOut])
def list_campaigns(
    db: DbDep,
    status: CampaignStatus | None = None,
    factory_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CampaignAdminOut]:
    """Cross-tenant campaign oversight for the staff console.

    Joins the owning factory and counts each campaign's draft (approval-pending)
    emails so staff see where the human send-gate (I3) is waiting.
    """
    pending = (
        select(Email.campaign_id, func.count(Email.id).label("pending"))
        .where(Email.status == EmailStatus.draft)
        .group_by(Email.campaign_id)
        .subquery()
    )
    query = (
        select(Campaign, Factory, func.coalesce(pending.c.pending, 0))
        .join(Factory, Factory.id == Campaign.factory_id)
        .outerjoin(pending, pending.c.campaign_id == Campaign.id)
        .order_by(Campaign.created_at.desc())
    )
    if status is not None:
        query = query.where(Campaign.status == status)
    if factory_id is not None:
        query = query.where(Campaign.factory_id == factory_id)
    query = query.offset(max(offset, 0)).limit(max(1, min(limit, 200)))
    return [
        CampaignAdminOut(
            id=c.id,
            name=c.name,
            factory_id=c.factory_id,
            factory_name_en=f.name_en,
            factory_name_ar=f.name_ar,
            market_iso2=c.market_iso2,
            status=c.status.value,
            paused_reason=c.paused_reason,
            prepared_by_staff=c.prepared_by_staff,
            total_emails=c.total_emails,
            sent_count=c.sent_count,
            opened_count=c.opened_count,
            replied_count=c.replied_count,
            bounced_count=c.bounced_count,
            complained_count=c.complained_count,
            pending_approvals=int(n),
            created_at=c.created_at,
        )
        for c, f, n in db.execute(query).all()
    ]


@router.post("/campaigns/{campaign_id}/pause", response_model=MessageResponse)
def pause_campaign(
    campaign_id: uuid.UUID, reason: str, db: DbDep, staff: User = Depends(require_staff)
) -> MessageResponse:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign.status = CampaignStatus.paused
    campaign.paused_reason = reason
    audit.record(
        db,
        action="campaign.paused_by_staff",
        entity_type="campaign",
        entity_id=campaign.id,
        actor=staff,
        factory_id=campaign.factory_id,
        payload={"reason": reason},
    )
    db.commit()
    return MessageResponse(detail="Campaign paused")


@router.post("/campaigns/{campaign_id}/resume", response_model=MessageResponse)
def resume_campaign(
    campaign_id: uuid.UUID, db: DbDep, staff: User = Depends(require_staff)
) -> MessageResponse:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign.status = CampaignStatus.active
    campaign.paused_reason = None
    audit.record(
        db,
        action="campaign.resumed_by_staff",
        entity_type="campaign",
        entity_id=campaign.id,
        actor=staff,
        factory_id=campaign.factory_id,
    )
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
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEntryOut]:
    query = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        query = query.where(AuditLog.action == action)
    if factory_id:
        query = query.where(AuditLog.factory_id == factory_id)
    query = query.offset(max(offset, 0)).limit(max(1, min(limit, 200)))
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

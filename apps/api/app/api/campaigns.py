"""Campaigns, the approval workflow, and the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DbDep, get_owned_campaign, get_owned_email, resolve_factory
from app.models import (
    Campaign,
    CampaignStatus,
    Email,
    EmailStatus,
    LIARecord,
    Market,
    Product,
    utcnow,
)
from app.schemas.campaign import (
    CampaignCreate,
    CampaignOut,
    DashboardStats,
    EmailEditRequest,
    EmailOut,
    LIACreateRequest,
    OutcomeReportRequest,
    RejectRequest,
)
from app.security import CurrentUser, assert_factory_access
from app.services import approval, sender_accounts
from app.workers.tasks import draft_campaign_emails, send_approved_email

router = APIRouter(tags=["campaigns"])


def _campaign_out(db: DbDep, campaign: Campaign) -> CampaignOut:
    """Serialize a campaign with the two approval-UI flags the row doesn't carry:
    whether its market is in the EU (a Legitimate Interest Assessment is then
    required before any send — I8) and whether a LIA has been recorded."""
    out = CampaignOut.model_validate(campaign)
    market = db.get(Market, campaign.market_iso2)
    out.market_is_eu = bool(market and market.is_eu)
    out.lia_recorded = (
        db.scalar(select(LIARecord.id).where(LIARecord.campaign_id == campaign.id)) is not None
    )
    return out


@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate, db: DbDep, user: CurrentUser) -> CampaignOut:
    product = db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    assert_factory_access(user, product.factory_id)

    # Hard prerequisite: a verified connected mailbox must exist before a campaign
    # can be created. The campaign is bound to it so every send is governed by
    # that specific account (daily limit, warm-up) in the worker.
    account = sender_accounts.default_verified_account(db, product.factory_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Connect and verify a sender mailbox before creating campaigns",
        )

    campaign = Campaign(
        factory_id=product.factory_id,
        product_id=product.id,
        sender_account_id=account.id,
        market_iso2=payload.market_iso2.upper(),
        name=payload.name,
        created_by=user.id,
        prepared_by_staff=user.factory_id is None,
    )
    db.add(campaign)
    db.commit()
    return _campaign_out(db, campaign)


@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns(db: DbDep, user: CurrentUser) -> list[CampaignOut]:
    factory = resolve_factory(db, user)
    rows = db.scalars(
        select(Campaign)
        .where(Campaign.factory_id == factory.id)
        .order_by(Campaign.created_at.desc())
    ).all()
    return [_campaign_out(db, c) for c in rows]


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(db: DbDep, campaign: Campaign = Depends(get_owned_campaign)) -> CampaignOut:
    return _campaign_out(db, campaign)


@router.post("/campaigns/{campaign_id}/draft", status_code=status.HTTP_202_ACCEPTED)
def draft_emails(campaign: Campaign = Depends(get_owned_campaign)) -> dict:
    draft_campaign_emails.delay(str(campaign.id))
    return {"detail": "Drafting started", "campaign_id": str(campaign.id)}


@router.get("/campaigns/{campaign_id}/emails", response_model=list[EmailOut])
def list_emails(
    db: DbDep,
    status_filter: str | None = None,
    campaign: Campaign = Depends(get_owned_campaign),
) -> list[EmailOut]:
    query = select(Email).where(Email.campaign_id == campaign.id).order_by(Email.created_at)
    if status_filter:
        query = query.where(Email.status == EmailStatus(status_filter))
    rows = db.scalars(query).all()
    return [EmailOut.model_validate(e) for e in rows]


@router.post("/campaigns/{campaign_id}/lia", status_code=status.HTTP_201_CREATED)
def create_lia(
    payload: LIACreateRequest,
    db: DbDep,
    user: CurrentUser,
    campaign: Campaign = Depends(get_owned_campaign),
) -> dict:
    """Record the Legitimate Interest Assessment required for EU markets."""
    existing = db.scalar(select(LIARecord).where(LIARecord.campaign_id == campaign.id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="LIA already recorded for this campaign")
    db.add(
        LIARecord(
            campaign_id=campaign.id,
            purpose_text=payload.purpose_text,
            necessity_text=payload.necessity_text,
            balancing_test_text=payload.balancing_test_text,
            data_sources=payload.data_sources,
            completed_by=user.id,
            completed_at=utcnow(),
        )
    )
    db.commit()
    return {"detail": "LIA recorded"}


@router.post("/campaigns/{campaign_id}/report", response_model=CampaignOut)
def report_outcome(
    payload: OutcomeReportRequest,
    db: DbDep,
    campaign: Campaign = Depends(get_owned_campaign),
) -> CampaignOut:
    if payload.reported_meetings is not None:
        campaign.reported_meetings = payload.reported_meetings
    if payload.reported_rfqs is not None:
        campaign.reported_rfqs = payload.reported_rfqs
    db.commit()
    return _campaign_out(db, campaign)


# --- The approval workflow -------------------------------------------------


@router.get("/emails/{email_id}", response_model=EmailOut)
def get_email(email: Email = Depends(get_owned_email)) -> EmailOut:
    return EmailOut.model_validate(email)


@router.put("/emails/{email_id}", response_model=EmailOut)
def edit_email(
    payload: EmailEditRequest,
    db: DbDep,
    user: CurrentUser,
    email: Email = Depends(get_owned_email),
) -> EmailOut:
    """Edit a draft. An approved email must first be reverted to draft, which
    clears its approval — so no edited message can retain a stale approval."""
    if email.status == EmailStatus.approved:
        approval.revert_to_draft(db, email, user)
    if email.status != EmailStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only draft emails can be edited (status: {email.status.value})",
        )
    if payload.subject is not None:
        email.subject = payload.subject[:512]
    if payload.body_text is not None:
        email.body_text = payload.body_text
        # Regenerate the HTML part from the edited text; otherwise the sent HTML
        # body would keep the stale, pre-edit (un-approved) content.
        from app.services.email_drafting import render_html_body

        email.body_html = render_html_body(email.body_text, email.unsubscribe_token, email.language)
    email.edited_by_user = True
    db.commit()
    return EmailOut.model_validate(email)


@router.post("/emails/{email_id}/approve", response_model=EmailOut)
def approve_email(
    db: DbDep, user: CurrentUser, email: Email = Depends(get_owned_email)
) -> EmailOut:
    approval.approve(db, email, user)
    db.commit()
    return EmailOut.model_validate(email)


@router.post("/emails/{email_id}/reject", response_model=EmailOut)
def reject_email(
    payload: RejectRequest,
    db: DbDep,
    user: CurrentUser,
    email: Email = Depends(get_owned_email),
) -> EmailOut:
    approval.reject(db, email, user, payload.note)
    db.commit()
    return EmailOut.model_validate(email)


@router.post("/emails/{email_id}/queue", response_model=EmailOut)
def queue_email(db: DbDep, user: CurrentUser, email: Email = Depends(get_owned_email)) -> EmailOut:
    """Approve-gated: only an approved email may be queued, and the pre-send
    gate (suppression + deliverability + EU LIA) runs here before the send task
    is dispatched."""
    approval.queue(db, email, user)
    db.commit()
    send_approved_email.delay(str(email.id))
    return EmailOut.model_validate(email)


@router.post("/campaigns/{campaign_id}/activate", response_model=CampaignOut)
def activate_campaign(db: DbDep, campaign: Campaign = Depends(get_owned_campaign)) -> CampaignOut:
    if campaign.status == CampaignStatus.draft:
        campaign.status = CampaignStatus.active
        db.commit()
    return _campaign_out(db, campaign)


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(db: DbDep, user: CurrentUser) -> DashboardStats:
    factory = resolve_factory(db, user)
    campaigns = db.scalars(select(Campaign).where(Campaign.factory_id == factory.id)).all()

    sent = sum(c.sent_count for c in campaigns)
    opened = sum(c.opened_count for c in campaigns)
    replied = sum(c.replied_count for c in campaigns)
    bounced = sum(c.bounced_count for c in campaigns)

    campaign_ids = [c.id for c in campaigns]
    pending = 0
    if campaign_ids:
        pending = (
            db.scalar(
                select(func.count(Email.id)).where(
                    Email.campaign_id.in_(campaign_ids), Email.status == EmailStatus.draft
                )
            )
            or 0
        )

    return DashboardStats(
        campaigns=len(campaigns),
        total_sent=sent,
        total_opened=opened,
        total_replied=replied,
        total_bounced=bounced,
        open_rate=round(opened / sent, 3) if sent else 0.0,
        reply_rate=round(replied / sent, 3) if sent else 0.0,
        bounce_rate=round(bounced / sent, 3) if sent else 0.0,
        pending_approvals=pending,
    )

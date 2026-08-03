"""Celery tasks: the discovery pipeline, the guarded send, and beat jobs.

Every task opens its own session scope and commits on success. The send task is
the guarded path — it delegates to ``services.sending.send_email``, which
re-verifies approval, suppression, and deliverability before the provider is
ever called.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db import session_scope
from app.logging import get_logger
from app.providers.registry import get_llm_provider, get_sending_provider
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.run_discovery")
def run_discovery(product_id: str, market_iso2: str) -> dict:
    from app.models import Product
    from app.services.buyer_discovery import discover_buyers
    from app.services.competitor_snapshot import build_snapshot

    with session_scope() as db:
        product = db.get(Product, uuid.UUID(product_id))
        if product is None:
            return {"error": "product not found"}
        summary = discover_buyers(db, product, market_iso2)
        if product.hs_code:
            build_snapshot(db, product.hs_code, market_iso2)
        return summary


@celery_app.task(name="app.workers.tasks.draft_campaign_emails")
def draft_campaign_emails(campaign_id: str) -> dict:
    from app.models import Campaign
    from app.services.email_drafting import draft_campaign

    with session_scope() as db:
        campaign = db.get(Campaign, uuid.UUID(campaign_id))
        if campaign is None:
            return {"error": "campaign not found"}
        created = draft_campaign(db, campaign, get_llm_provider())
        return {"campaign_id": campaign_id, "drafts_created": created}


@celery_app.task(name="app.workers.tasks.send_approved_email")
def send_approved_email(email_id: str) -> dict:
    """Send a single queued+approved email through the guarded path.

    When the campaign has a connected mailbox, the send goes out through that
    account (refreshing its OAuth token first, and pausing safely if the mailbox
    needs reconnection); otherwise the legacy shared cold-email provider is used.
    """
    from app.models import Campaign, Email, SenderAccount
    from app.providers.registry import get_mailbox_provider
    from app.services import sender_oauth
    from app.services.sending import AccountBoundSender, SendBlocked, send_email

    eid = uuid.UUID(email_id)
    with session_scope() as db:
        email = db.get(Email, eid)
        if email is None:
            return {"email_id": email_id, "sent": False, "reason": "email not found"}
        campaign = db.get(Campaign, email.campaign_id)
        account = (
            db.get(SenderAccount, campaign.sender_account_id)
            if campaign and campaign.sender_account_id
            else None
        )

        if account is not None:
            try:
                creds = sender_oauth.ensure_valid_credentials(db, account)
            except sender_oauth.ReauthRequired as exc:
                # ensure_valid_credentials already paused campaigns + notified +
                # audited; persist that and stop — never fail silently.
                log.info("send_blocked_reauth", email_id=email_id, reason=str(exc))
                return {"email_id": email_id, "sent": False, "reason": "needs_reauth"}
            sender = AccountBoundSender(get_mailbox_provider(account.provider_type.value), creds)
        else:
            sender = get_sending_provider()

        try:
            email = send_email(db, eid, sender)
        except SendBlocked as exc:
            log.info("send_blocked", email_id=email_id, reason=str(exc))
            return {"email_id": email_id, "sent": False, "reason": str(exc)}
        return {"email_id": email_id, "sent": email.status.value == "sent"}


@celery_app.task(name="app.workers.tasks.process_followups")
def process_followups() -> dict:
    """Create follow-up *drafts* for sent-but-unanswered emails.

    Follow-ups are never auto-sent; they enter the same approval queue as any
    other draft.
    """
    import secrets
    from datetime import timedelta

    from app.models import Email, EmailStatus, utcnow
    from app.services.email_drafting import unsubscribe_url  # noqa: F401 (parity import)

    cutoff = utcnow() - timedelta(days=4)
    created = 0
    with session_scope() as db:
        candidates = db.scalars(
            select(Email).where(
                Email.status == EmailStatus.sent,
                Email.sent_at < cutoff,
                Email.is_followup.is_(False),
            )
        ).all()
        for original in candidates:
            already = db.scalar(
                select(Email.id).where(
                    Email.parent_email_id == original.id,
                    Email.followup_number == 1,
                )
            )
            if already:
                continue
            db.add(
                Email(
                    campaign_id=original.campaign_id,
                    contact_id=original.contact_id,
                    buyer_id=original.buyer_id,
                    status=EmailStatus.draft,
                    subject=f"Re: {original.subject}",
                    body_text=_followup_body(original.body_text),
                    body_html=original.body_html,
                    language=original.language,
                    is_followup=True,
                    followup_number=1,
                    parent_email_id=original.id,
                    unsubscribe_token=secrets.token_urlsafe(24),
                )
            )
            created += 1
    return {"followup_drafts_created": created}


@celery_app.task(name="app.workers.tasks.evaluate_deliverability")
def evaluate_deliverability() -> dict:
    from app.models import Campaign, CampaignStatus
    from app.services.deliverability import evaluate_campaign_health

    paused = 0
    with session_scope() as db:
        active = db.scalars(select(Campaign).where(Campaign.status == CampaignStatus.active)).all()
        for campaign in active:
            if evaluate_campaign_health(db, campaign):
                paused += 1
    return {"campaigns_auto_paused": paused}


@celery_app.task(name="app.workers.tasks.reset_daily_counters")
def reset_daily_counters() -> dict:
    from app.models import Factory, SenderAccount, utcnow

    with session_scope() as db:
        factories = db.scalars(select(Factory)).all()
        for factory in factories:
            factory.daily_send_count = 0
            factory.daily_counter_date = utcnow()
        accounts = db.scalars(select(SenderAccount)).all()
        for account in accounts:
            account.daily_sent_count = 0
            account.daily_counter_date = utcnow()
    return {"factories_reset": len(factories), "sender_accounts_reset": len(accounts)}


@celery_app.task(name="app.workers.tasks.advance_sender_warmup")
def advance_sender_warmup() -> dict:
    """Ramp each connected mailbox one warm-up stage per day (per the schedule)."""
    from app.models import SenderAccount, SenderVerificationStatus
    from app.services import sender_accounts

    advanced = 0
    with session_scope() as db:
        accounts = db.scalars(
            select(SenderAccount).where(
                SenderAccount.verification_status == SenderVerificationStatus.verified
            )
        ).all()
        for account in accounts:
            if sender_accounts.advance_warmup(db, account):
                advanced += 1
    return {"sender_accounts_advanced": advanced}


@celery_app.task(name="app.workers.tasks.poll_replies")
def poll_replies() -> dict:
    """Poll every verified mailbox for replies and stop replied contacts' sequences.

    Read scope only. On reply, the contact's remaining sequence is stopped and a
    notification is created (see ``services.replies``).
    """
    from datetime import timedelta

    from app.config import get_settings
    from app.models import SenderAccount, SenderVerificationStatus, utcnow
    from app.providers.registry import get_mailbox_provider
    from app.services import replies, sender_oauth

    settings = get_settings()
    matched = 0
    polled = 0
    with session_scope() as db:
        accounts = db.scalars(
            select(SenderAccount).where(
                SenderAccount.verification_status == SenderVerificationStatus.verified
            )
        ).all()
        for account in accounts:
            try:
                creds = sender_oauth.ensure_valid_credentials(db, account)
            except sender_oauth.ReauthRequired:
                continue  # account paused + notified; skip until reconnected
            since = account.last_polled_at or (
                utcnow() - timedelta(minutes=settings.reply_poll_lookback_minutes)
            )
            provider = get_mailbox_provider(account.provider_type.value)
            matched += replies.poll_account(db, account, provider, creds, since)
            polled += 1
    return {"mailboxes_polled": polled, "replies_matched": matched}


@celery_app.task(name="app.workers.tasks.advance_warmup")
def advance_warmup() -> dict:
    from app.config import get_settings
    from app.models import Factory

    settings = get_settings()
    advanced = 0
    with session_scope() as db:
        warming = db.scalars(select(Factory).where(Factory.warmup_started_at.is_not(None))).all()
        for factory in warming:
            if factory.warmup_day < settings.warmup_days:
                factory.warmup_day += 1
                advanced += 1
    return {"factories_advanced": advanced}


def _followup_body(original_body: str) -> str:
    intro = (
        "I wanted to gently follow up on my note below in case it slipped past. "
        "I'd be glad to send a sample or a price list whenever it's useful.\n\n"
    )
    return intro + original_body

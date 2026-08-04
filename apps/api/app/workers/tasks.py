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
    from app.services.api_budget import budget_scope
    from app.services.buyer_discovery import discover_buyers
    from app.services.competitor_snapshot import build_snapshot

    with session_scope() as db:
        product = db.get(Product, uuid.UUID(product_id))
        if product is None:
            return {"error": "product not found"}
        # I2 (defense-in-depth) — never run discovery on an unconfirmed HS code,
        # even for a job enqueued directly (bypassing the API gate). Degrade
        # gracefully rather than raising, matching the "product not found" style.
        if not (product.hs_code and product.hs_confirmed_by_user):
            return {"error": "hs code not confirmed"}
        # Re-establish the per-analysis live-call budget inside the worker (I5-style
        # contextvar; does not cross the process boundary) so the competitor
        # snapshot's live Comtrade calls are capped and logged (locked decision #5).
        with budget_scope(label=f"discovery:{product_id}:{market_iso2}"):
            summary = discover_buyers(db, product, market_iso2)
            if product.hs_code:
                build_snapshot(db, product.hs_code, market_iso2)
        return summary


@celery_app.task(name="app.workers.tasks.classify_product_hs")
def classify_product_hs(product_name: str, deepen: bool = False) -> dict:
    """Propose HS6 candidates for a product name via the engine (pipeline step 2).

    Wires the Celery worker directly to ``silk_intel`` (locked decision #2) and
    re-establishes the ``/deepen`` scope from the explicit payload flag (invariant
    I5 — ``contextvars`` do not cross the process boundary). Output is a *proposal*
    with confidence + ranked alternatives, each carrying its provenance envelope;
    the human-confirmation gate (I2) is enforced before any code is committed —
    this task never auto-commits an HS classification.
    """
    from app.services import engine

    with engine.deepen_scope(deepen):
        candidates = engine.resolve_hs_candidates(product_name)
    return {
        "product_name": product_name,
        "deepen": deepen,
        "proposals": [c.as_dict() for c in candidates],
    }


@celery_app.task(name="app.workers.tasks.run_hs_analysis")
def run_hs_analysis(product_id: str, deepen: bool = False) -> dict:
    """Classify a product via the engine and persist the run to Postgres (I1/I2/I5).

    Opens its own session scope (like ``run_discovery``), loads the product,
    resolves HS6 proposals through ``silk_intel`` inside the re-established
    ``/deepen`` scope, and persists an ``Analysis`` + one ``HSClassification`` per
    ranked candidate, each with its full provenance envelope. Proposals are stored
    unconfirmed — the human-confirm gate is not bypassed.
    """
    import uuid as _uuid

    from app.models import Product
    from app.services.analysis import classify_and_persist

    with session_scope() as db:
        product = db.get(Product, _uuid.UUID(product_id))
        if product is None:
            return {"error": "product not found"}
        analysis = classify_and_persist(db, product, deepen=deepen)
        db.flush()
        return {
            "analysis_id": str(analysis.id),
            "status": analysis.status,
            "deepen": deepen,
        }


@celery_app.task(name="app.workers.tasks.run_world_ranking")
def run_world_ranking(analysis_id: str, hs6: str, top_n: int = 20) -> dict:
    """Screen the world for a confirmed HS6 and persist the country shortlist.

    Stage 1 of the world funnel: reads the precomputed ``world_trade`` table and
    persists the ranked markets (with transit-port flags + provenance, I9/I1)
    against the analysis. ``hs6`` is the human-confirmed code (I2) — the caller
    passes it explicitly; this task never re-classifies.
    """
    import uuid as _uuid

    from app.models import Analysis
    from app.services.api_budget import budget_scope
    from app.services.ranking import rank_and_persist

    with session_scope() as db:
        analysis = db.get(Analysis, _uuid.UUID(analysis_id))
        if analysis is None:
            return {"error": "analysis not found"}
        # Stage 1 is a local SQL screen (no live calls), but the same scope caps
        # the budgeted live enrichment that Stages 2-3 add on top (decision #5).
        with budget_scope(label=f"ranking:{analysis_id}:{hs6}"):
            rankings = rank_and_persist(db, analysis, hs6, top_n=top_n)
        if analysis.status in ("pending", "classified"):
            analysis.status = "ranked"
        db.flush()
        return {
            "analysis_id": analysis_id,
            "hs6": hs6,
            "ranked": len(rankings),
            "top5": [r.importer_iso3 for r in rankings[:5]],
        }


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


@celery_app.task(name="app.workers.tasks.run_pdpl_retention")
def run_pdpl_retention() -> dict:
    """PDPL data-minimisation sweep: anonymise personal data on contacts whose
    campaign work is done and that are older than the retention window."""
    from app.services import retention

    with session_scope() as db:
        anonymised = retention.purge_stale_pii(db)
    return {"contacts_anonymised": anonymised}


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

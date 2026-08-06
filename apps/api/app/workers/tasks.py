"""Celery tasks: the discovery pipeline, the guarded send, and beat jobs.

Every task opens its own session scope and commits on success. The send task is
the guarded path — it delegates to ``services.sending.send_email``, which
re-verifies approval, suppression, and deliverability before the provider is
ever called.
"""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, OperationalError

from app.db import SessionLocal, session_scope
from app.logging import get_logger
from app.providers.registry import get_llm_provider, get_sending_provider
from app.workers.celery_app import celery_app

log = get_logger(__name__)

#: Errors worth retrying with backoff — transient infrastructure/vendor faults
#: (network blips, timeouts, 429/5xx, dropped DB connections). Everything else is
#: treated as a permanent failure and marked failed immediately (no retry storm).
_TRANSIENT_EXC = (
    httpx.TimeoutException,
    httpx.TransportError,
    httpx.HTTPStatusError,
    OperationalError,
    DBAPIError,
    ConnectionError,
    TimeoutError,
)
#: Retry policy for the pipeline tasks.
_MAX_RETRIES = 3
_RETRY_BACKOFF = 5  # seconds, doubled each attempt (5s, 10s, 20s)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        # Only 429 + 5xx are transient; a 4xx (bad request/auth) will not fix
        # itself on retry.
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, _TRANSIENT_EXC)


def _mark_product_failed(product_id: str, reason: str) -> None:
    """Persist a terminal failure on a product in its own short transaction."""
    from app.models import Product

    with session_scope() as db:
        product = db.get(Product, uuid.UUID(product_id))
        if product is not None:
            product.classification_status = "failed"
            product.failure_reason = reason[:500]


def _mark_analysis_failed(analysis_id: str, reason: str) -> None:
    """Persist a terminal failure on an analysis in its own short transaction."""
    from app.models import Analysis

    with session_scope() as db:
        analysis = db.get(Analysis, uuid.UUID(analysis_id))
        if analysis is not None:
            analysis.status = "failed"
            analysis.failure_reason = reason[:500]


def _handle_pipeline_failure(task, analysis_id: str, stage: str, exc: Exception):
    """Retry a transient analysis-stage fault, else mark it failed and re-raise.

    Shared by the three world-funnel stage tasks. ``session_scope`` has already
    rolled back the failed transaction; this opens a fresh one only to record the
    terminal state, so the failure is always persisted and visible.
    """
    if _is_transient(exc) and task.request.retries < _MAX_RETRIES:
        log.warning(
            f"{stage}_retry",
            analysis_id=analysis_id,
            attempt=task.request.retries + 1,
            error=str(exc),
        )
        raise task.retry(exc=exc, countdown=_RETRY_BACKOFF * (2**task.request.retries))
    log.error(f"{stage}_failed", analysis_id=analysis_id, error=str(exc))
    _mark_analysis_failed(analysis_id, f"{stage}: {type(exc).__name__}: {exc}")
    raise exc


@celery_app.task(name="app.workers.tasks.run_discovery")
def run_discovery(product_id: str, market_iso2: str, analysis_id: str | None = None) -> dict:
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
            summary = discover_buyers(
                db,
                product,
                market_iso2,
                # Decision #6 / I8 — the analysis this fetch serves crosses the
                # process boundary explicitly in the task payload, like deepen.
                analysis_id=uuid.UUID(analysis_id) if analysis_id else None,
            )
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


@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_product_intake",
    max_retries=_MAX_RETRIES,
)
def process_product_intake(self, product_id: str, deepen: bool = False) -> dict:
    """Pipeline steps 1-2 for one product: vision → HS proposal → embedding (I5).

    Mirrors the old inline body of ``products.create_product`` exactly, but in the
    worker. The ``/deepen`` scope is re-established from the explicit ``deepen``
    payload flag (invariant I5 — ``contextvars`` do NOT cross the process boundary,
    and eager mode must not bypass this): the vision pass fills the AR/EN
    description + attributes (DoD step 1), the engine proposes HS6 candidates
    (I2 — proposal only, ``product.hs_code`` is never set here), and the product
    embedding is computed exactly as the inline route did. Opens its own session
    and commits on success.

    On a transient vendor/DB fault it retries with backoff; on a permanent fault
    (or once retries are exhausted) it records a terminal ``failed`` status with a
    reason so the UI reaches a terminal state instead of polling ``pending``
    forever — and the user can retry or enter an HS code manually.
    """
    import uuid as _uuid

    from app.models import Product
    from app.providers.registry import get_embedding_provider, get_llm_provider
    from app.services import engine, hs_classifier, product_vision

    db = SessionLocal()
    try:
        product = db.get(Product, _uuid.UUID(product_id))
        if product is None:
            return {"error": "product not found"}
        with engine.deepen_scope(deepen):
            # Vision is a best-effort enrichment (fills the AR/EN description +
            # attributes). HS classification is name-based (the engine resolver,
            # no LLM), so a vision failure — a live LLM error, a bad ANTHROPIC_MODEL,
            # a timeout — must NEVER block the HS proposal. Degrade to no vision
            # enrichment and press on to classify, rather than crashing the whole
            # intake and leaving the product stuck with no HS candidates.
            try:
                product_vision.describe_product(db, product, get_llm_provider())
            except Exception as exc:  # noqa: BLE001 — best-effort; reason is logged
                log.warning("product_vision_skipped", product_id=product_id, error=str(exc))
            hs_classifier.classify_product(db, product)
            embedding = get_embedding_provider().embed(
                [f"{product.name_en} {product.description_en or ''}"]
            )[0]
            product.embedding = embedding
        db.commit()
        return {
            "product_id": product_id,
            "classification_status": product.classification_status,
            "deepen": deepen,
        }
    except Exception as exc:
        db.rollback()
        if _is_transient(exc) and self.request.retries < _MAX_RETRIES:
            log.warning(
                "product_intake_retry",
                product_id=product_id,
                attempt=self.request.retries + 1,
                error=str(exc),
            )
            raise self.retry(exc=exc, countdown=_RETRY_BACKOFF * (2**self.request.retries)) from exc
        log.error("product_intake_failed", product_id=product_id, error=str(exc))
        _mark_product_failed(product_id, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="app.workers.tasks.run_world_ranking", max_retries=_MAX_RETRIES)
def run_world_ranking(
    self, analysis_id: str, hs6: str, top_n: int = 20, deepen: bool = False
) -> dict:
    """Screen the world for a confirmed HS6 and persist the country shortlist.

    Stage 1 of the world funnel: reads the precomputed ``world_trade`` table and
    persists the ranked markets (with transit-port flags + provenance, I9/I1)
    against the analysis. ``hs6`` is the human-confirmed code (I2) — the caller
    passes it explicitly; this task never re-classifies. The ``/deepen`` scope is
    re-established from the explicit ``deepen`` payload flag (I5) so any budgeted
    paid enrichment folded into the screen is gated in-process.

    Retries transient faults with backoff; on permanent failure marks the
    analysis ``failed`` (with a reason) so it never stalls in a non-terminal state.
    """
    import uuid as _uuid

    from app.models import Analysis
    from app.services import engine, world_funnel
    from app.services.api_budget import budget_scope
    from app.services.ranking import rank_and_persist

    try:
        with session_scope() as db:
            analysis = db.get(Analysis, _uuid.UUID(analysis_id))
            if analysis is None:
                return {"error": "analysis not found"}
            # Fail loudly on missing coverage: an empty world_trade for this HS6
            # would otherwise produce a silent empty funnel presented as a real
            # world screen. Mark the analysis failed with an actionable reason and
            # request a coverage sync so a retry has data.
            coverage = world_funnel.coverage_state(db, hs6)
            if coverage == "none":
                analysis.status = "failed"
                analysis.failure_reason = (
                    f"No world-trade data for HS {hs6}. A coverage sync has been "
                    "requested — please retry in a few minutes."
                )
                db.flush()
                sync_world_trade.delay(hs6)
                log.warning("world_ranking_no_coverage", analysis_id=analysis_id, hs6=hs6)
                return {"analysis_id": analysis_id, "hs6": hs6, "coverage": "none", "ranked": 0}
            # Stage 1 is a local SQL screen (no live calls), but the same scope
            # caps the budgeted live enrichment Stages 2-3 add on top (decision
            # #5), and the deepen scope (I5) gates paid engine agents behind
            # /deepen.
            with engine.deepen_scope(deepen), budget_scope(label=f"ranking:{analysis_id}:{hs6}"):
                rankings = rank_and_persist(db, analysis, hs6, top_n=top_n)
                if analysis.status in ("pending", "classified"):
                    analysis.status = "ranked"
            db.flush()
            if coverage == "demo":
                # Real screen structure, demo data underneath — request a live sync
                # so the next run upgrades it; the caller sees coverage=='demo'.
                sync_world_trade.delay(hs6)
                log.warning("world_ranking_demo_coverage", analysis_id=analysis_id, hs6=hs6)
            return {
                "analysis_id": analysis_id,
                "hs6": hs6,
                "coverage": coverage,
                "ranked": len(rankings),
                "top5": [r.importer_iso3 for r in rankings[:5]],
                "deepen": deepen,
            }
    except Exception as exc:
        return _handle_pipeline_failure(self, analysis_id, "world_ranking", exc)


@celery_app.task(bind=True, name="app.workers.tasks.run_stage2_enrich", max_retries=_MAX_RETRIES)
def run_stage2_enrich(self, analysis_id: str, hs6: str, deepen: bool = False) -> dict:
    """Funnel Stage 2 in the worker: budgeted enrichment of the shortlist → top 5.

    Mirrors ``analyses.enrich_analysis``'s old inline body. The ``/deepen`` scope
    is re-established from the explicit ``deepen`` payload flag (invariant I5) and
    the per-analysis API budget (decision #5) is re-opened in-process; inside both
    scopes ``enrich_shortlist`` enriches the persisted Stage-1 shortlist and
    re-ranks it, and the analysis is marked ``enriched``. Opens its own session
    and commits on success. Retries transient faults; marks ``failed`` on a
    permanent one.
    """
    import uuid as _uuid

    from app.models import Analysis
    from app.services import engine
    from app.services.api_budget import budget_scope
    from app.services.stage2 import enrich_shortlist

    db = SessionLocal()
    try:
        analysis = db.get(Analysis, _uuid.UUID(analysis_id))
        if analysis is None:
            return {"error": "analysis not found"}
        with engine.deepen_scope(deepen), budget_scope(label=f"stage2:{analysis_id}"):
            enrich_shortlist(db, analysis, hs6)
            if analysis.status in ("pending", "classified", "ranked"):
                analysis.status = "enriched"
        db.commit()
        # Auto-chain Stage 3 (FREE per-market deep-dive). Commit-before-enqueue so
        # the Stage-3 task's own session sees the enriched rows; eager mode runs it
        # inline (tests), prod queues it. deepen is carried forward (stays False).
        run_stage3_deepdive.delay(analysis_id, hs6, deepen=deepen)
        return {
            "analysis_id": analysis_id,
            "hs6": hs6,
            "status": analysis.status,
            "deepen": deepen,
        }
    except Exception as exc:
        db.rollback()
        return _handle_pipeline_failure(self, analysis_id, "stage2_enrich", exc)
    finally:
        db.close()


@celery_app.task(bind=True, name="app.workers.tasks.run_stage3_deepdive", max_retries=_MAX_RETRIES)
def run_stage3_deepdive(self, analysis_id: str, hs6: str, deepen: bool = False) -> dict:
    """Funnel Stage 3 in the worker: FREE per-market deep-dive of the top-5.

    Mirrors ``run_stage2_enrich``'s scope discipline. The ``/deepen`` scope is
    re-established from the explicit ``deepen`` payload flag (invariant I5) — the
    auto sweep keeps ``deepen=False`` so the paid engine agents + ``observed_prices``
    structurally skip — and the per-analysis API budget (decision #5) is re-opened
    in-process. Inside both scopes ``deepdive_shortlist`` deep-dives the persisted
    Stage-2 finalists with the engine's free offline layers (competitors,
    requirements, correlation threads) and the analysis reaches the terminal
    ``deepened`` status. Opens its own session and commits on success. Retries
    transient faults; marks ``failed`` on a permanent one.
    """
    import uuid as _uuid

    from app.models import Analysis, Product
    from app.services import engine
    from app.services.api_budget import budget_scope
    from app.services.stage3 import deepdive_shortlist

    db = SessionLocal()
    try:
        analysis = db.get(Analysis, _uuid.UUID(analysis_id))
        if analysis is None:
            return {"error": "analysis not found"}
        product = db.get(Product, analysis.product_id) if analysis.product_id else None
        with engine.deepen_scope(deepen), budget_scope(label=f"stage3:{analysis_id}"):
            deepdive_shortlist(db, analysis, hs6, product)
            analysis.status = "deepened"
        db.commit()
        return {
            "analysis_id": analysis_id,
            "hs6": hs6,
            "status": analysis.status,
            "deepen": deepen,
        }
    except Exception as exc:
        db.rollback()
        return _handle_pipeline_failure(self, analysis_id, "stage3_deepdive", exc)
    finally:
        db.close()


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


@celery_app.task(name="app.workers.tasks.sync_world_trade")
def sync_world_trade(hs6: str) -> dict:
    """Refresh ``world_trade`` Stage-1 coverage for one HS6 from UN Comtrade.

    Fail-closed (the PR #83 pattern): the live bulk download runs only when a real
    ``COMTRADE_API_KEY`` is configured and offline mode is off. Otherwise it does
    NOT fabricate coverage — it records that live data is unavailable and returns,
    so an offline/demo deployment never presents synthesized data as a real world
    screen. The heavy pandas + comtradeapicall download lives in ``etl`` (I7);
    this task is the product-side trigger that invokes it.
    """
    from app.config import get_settings

    settings = get_settings()
    code = (hs6 or "").strip()
    if not code:
        return {"hs6": hs6, "synced": False, "reason": "empty hs6"}
    if settings.comtrade_offline or not settings.comtrade_api_key:
        log.warning("world_trade_sync_unavailable", hs6=code, reason="no live comtrade key")
        return {"hs6": code, "synced": False, "reason": "live comtrade unavailable"}
    try:
        from etl import world_trade_sync

        written = world_trade_sync.run(code)
    except ImportError as exc:
        # The heavy bulk download lives in the ``etl`` environment (pandas +
        # comtradeapicall, I7). If that environment is not present, degrade
        # loudly rather than fabricate coverage.
        log.error("world_trade_sync_env_missing", hs6=code, error=str(exc))
        return {"hs6": code, "synced": False, "reason": "etl environment unavailable"}
    except Exception as exc:  # noqa: BLE001 — a failed sync is a declared gap, not a crash
        log.error("world_trade_sync_failed", hs6=code, error=str(exc))
        return {"hs6": code, "synced": False, "reason": str(exc)}
    log.info("world_trade_synced", hs6=code, rows=written)
    return {"hs6": code, "synced": True, "rows": written}


@celery_app.task(name="app.workers.tasks.refresh_world_trade")
def refresh_world_trade() -> dict:
    """Scheduled sweep: re-sync world_trade for HS6 codes in active use.

    Enqueues a per-HS6 :func:`sync_world_trade` for every confirmed product whose
    coverage is missing or stale (older than ``world_trade_refresh_days``), so the
    Stage-1 data stays current for the codes customers actually screen. The sync
    itself is fail-closed, so this is a no-op on an offline/keyless deployment.
    """
    from datetime import timedelta

    from app.config import get_settings
    from app.models import Product, WorldTrade, utcnow

    settings = get_settings()
    cutoff = utcnow() - timedelta(days=settings.world_trade_refresh_days)
    requested = 0
    with session_scope() as db:
        confirmed_hs6 = set(
            db.scalars(
                select(func.distinct(Product.hs_code)).where(
                    Product.hs_code.is_not(None),
                    Product.hs_confirmed_by_user.is_(True),
                )
            ).all()
        )
        for hs6 in confirmed_hs6:
            newest = db.scalar(select(func.max(WorldTrade.fetched_at)).where(WorldTrade.hs6 == hs6))
            if newest is None or newest < cutoff:
                sync_world_trade.delay(hs6)
                requested += 1
    if requested:
        log.info("world_trade_refresh_requested", codes=requested)
    return {"sync_requested": requested}


@celery_app.task(name="app.workers.tasks.reap_stale_sends")
def reap_stale_sends() -> dict:
    """Resolve email sends stuck mid-flight after a worker was lost.

    See ``services.sending.reap_stale_sends`` — interrupted claims are moved to a
    terminal state (never auto-retried) so a possibly-delivered message is not
    sent twice, and the factory is notified so it is not an invisible lost sale.
    """
    from app.config import get_settings
    from app.services.sending import reap_stale_sends as _reap

    settings = get_settings()
    with session_scope() as db:
        reaped = _reap(db, settings.send_claim_stale_seconds)
    return {"reaped": reaped}


@celery_app.task(name="app.workers.tasks.reconcile_stuck_analyses")
def reconcile_stuck_analyses() -> dict:
    """Fail analyses stuck in a non-terminal status past the staleness window.

    A worker lost to OOM/SIGKILL (or a task that died before marking failure)
    leaves the analysis in ``pending``/``ranked``/``enriched`` forever. This sweep
    moves such rows to ``failed`` with a reason so the UI shows a terminal state
    and the user can re-run — instead of an invisible, permanently broken funnel.
    """
    from datetime import timedelta

    from app.config import get_settings
    from app.models import Analysis, utcnow

    settings = get_settings()
    cutoff = utcnow() - timedelta(minutes=settings.analysis_stuck_minutes)
    non_terminal = ("pending", "classified", "ranked", "enriched")
    failed = 0
    with session_scope() as db:
        stuck = db.scalars(
            select(Analysis).where(
                Analysis.status.in_(non_terminal),
                Analysis.updated_at < cutoff,
            )
        ).all()
        for analysis in stuck:
            prev = analysis.status
            analysis.status = "failed"
            analysis.failure_reason = (
                f"stalled in '{prev}' for over "
                f"{settings.analysis_stuck_minutes} min (worker lost); please re-run"
            )
            failed += 1
    if failed:
        log.warning("stuck_analyses_reconciled", count=failed)
    return {"failed": failed}


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

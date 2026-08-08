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

#: Word (.docx) media type — shared by the report-render tasks.
_RESEARCH_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        # Only 429 + 5xx are transient; a 4xx (bad request/auth) will not fix
        # itself on retry.
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    # Celery's soft time limit is billiard's own class — NOT a TimeoutError
    # subclass — so it used to be classified permanent: one slow vendor pass
    # failed the whole analysis with the truncated reason
    # "SoftTimeLimitExceeded: " (str() is empty). A timeout is the definition
    # of transient; the retry budget (_MAX_RETRIES) keeps it bounded.
    from billiard.exceptions import SoftTimeLimitExceeded

    if isinstance(exc, SoftTimeLimitExceeded):
        return True
    return isinstance(exc, _TRANSIENT_EXC)


def _describe_failure(exc: Exception) -> str:
    """Human-readable failure text for persisted failure_reason fields.

    ``SoftTimeLimitExceeded`` stringifies to "" — the persisted reason ended in
    a bare colon. Name the actual limit instead so the user (and the operator)
    see what bound was hit.
    """
    from billiard.exceptions import SoftTimeLimitExceeded

    if isinstance(exc, SoftTimeLimitExceeded):
        from app.config import get_settings

        return (
            f"stage exceeded the {get_settings().task_soft_time_limit_seconds}s "
            "time limit (slow external data source); retries exhausted"
        )
    return f"{type(exc).__name__}: {exc}"


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
    _mark_analysis_failed(analysis_id, f"{stage}: {_describe_failure(exc)}")
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
        # I2 (defense-in-depth, ADR-0009) — never run discovery on an uncommitted
        # HS code (human confirm or strict-auto commit both qualify), even for a
        # job enqueued directly (bypassing the API gate). Degrade gracefully
        # rather than raising, matching the "product not found" style.
        if not product.hs_ready:
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
    description + attributes (DoD step 1), the engine proposes HS6 candidates —
    committing the code itself only on the engine's strict ``tier="auto"``
    verdict, provenance-tagged and never over a human confirmation (I2 as
    amended by ADR-0009) — and the product embedding is computed exactly as the
    inline route did. Opens its own session and commits on success.

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
    self,
    analysis_id: str,
    hs6: str,
    top_n: int | None = None,
    deepen: bool = False,
    after_sync: bool = False,
) -> dict:
    """Screen the world for a confirmed HS6 and persist the country shortlist.

    Stage 1 of the world funnel: reads the precomputed ``world_trade`` table and
    persists the ranked markets (with transit-port flags + provenance, I9/I1)
    against the analysis. ``hs6`` is the human-confirmed code (I2) — the caller
    passes it explicitly; this task never re-classifies. The ``/deepen`` scope is
    re-established from the explicit ``deepen`` payload flag (I5) so any budgeted
    paid enrichment folded into the screen is gated in-process.

    Missing coverage with a live Comtrade source is a TRANSIENT state, not a
    terminal failure: the analysis stays ``pending`` and a coverage sync bound to
    it is enqueued; :func:`sync_world_trade` re-dispatches this task (with
    ``after_sync=True``) once rows land, so the funnel completes with zero manual
    retries — the recurring «please retry in a few minutes» dead-end. The
    ``after_sync`` flag bounds the chain to ONE cycle: still-missing coverage
    after a completed sync is a terminal, truthfully-worded failure (I1 — no
    fabricated screen, no false retry promise).

    Retries transient faults with backoff; on permanent failure marks the
    analysis ``failed`` (with a reason) so it never stalls in a non-terminal state.
    """
    import uuid as _uuid

    from app.models import Analysis
    from app.services import engine, heartbeat, world_funnel
    from app.services.api_budget import budget_scope
    from app.services.ranking import rank_and_persist

    try:
        with session_scope() as db:
            analysis = db.get(Analysis, _uuid.UUID(analysis_id))
            if analysis is None:
                return {"error": "analysis not found"}
            # Loud, honest handling of missing coverage: an empty world_trade for
            # this HS6 would otherwise produce a silent empty funnel presented as
            # a real world screen (I1). With a LIVE Comtrade source the state is
            # transient — keep the analysis pending and chain a sync bound to it
            # (sync_world_trade re-dispatches this task when rows land), so the
            # user's single click completes without the recurring manual
            # «retry in a few minutes» dance. Without a live source — or when a
            # completed sync still produced nothing (after_sync) — the state is
            # terminal: say so truthfully, never promise a retry that cannot help,
            # and never fabricate a screen.
            coverage = world_funnel.coverage_state(db, hs6)
            if coverage == "none":
                from app.config import get_settings

                settings = get_settings()
                live_available = bool(settings.comtrade_api_key) and not settings.comtrade_offline
                if live_available and not after_sync:
                    # Transient: hold the pending state (the UI keeps polling this
                    # very analysis) and refresh liveness so the stuck-row reaper
                    # leaves it alone while the sync runs. Commit BEFORE
                    # dispatching the bound sync: in eager mode the whole chain
                    # (sync → re-rank) executes inline, and this session's
                    # uncommitted hold would otherwise overwrite the chained
                    # task's 'ranked' write on exit.
                    analysis.failure_reason = None
                    heartbeat.beat(analysis.id)
                    db.flush()
                    db.commit()
                    log.warning(
                        "world_ranking_awaiting_coverage_sync",
                        analysis_id=analysis_id,
                        hs6=hs6,
                    )
                    sync_world_trade.delay(
                        hs6, analysis_id=analysis_id, top_n=top_n, deepen=deepen
                    )
                    return {
                        "analysis_id": analysis_id,
                        "hs6": hs6,
                        "coverage": "none",
                        "ranked": 0,
                        "live_available": True,
                        "sync_requested": True,
                    }
                else:
                    analysis.status = "failed"
                    if live_available:
                        analysis.failure_reason = (
                            f"The live Comtrade sync completed but produced no "
                            f"world-trade rows for HS {hs6} — the world may not "
                            "report this code. Check the HS code (or re-run the "
                            "screen later); no figures are invented."
                        )
                    else:
                        analysis.failure_reason = (
                            f"World-market screening is unavailable for HS {hs6} on "
                            "this deployment: no live trade-data source is connected, "
                            "so there is nothing to screen and no figures are "
                            "invented. Operator: set COMTRADE_API_KEY (UN Comtrade) to "
                            "enable real world-trade coverage."
                        )
                    db.flush()
                    log.warning(
                        "world_ranking_no_coverage",
                        analysis_id=analysis_id,
                        hs6=hs6,
                        live_available=live_available,
                        after_sync=after_sync,
                    )
                    return {
                        "analysis_id": analysis_id,
                        "hs6": hs6,
                        "coverage": "none",
                        "ranked": 0,
                        "live_available": live_available,
                    }
            # Stage 1 is a local SQL screen (no live calls), but the same scope
            # caps the budgeted live enrichment Stages 2-3 add on top (decision
            # #5), and the deepen scope (I5) gates paid engine agents behind
            # /deepen.
            with engine.deepen_scope(deepen), budget_scope(label=f"ranking:{analysis_id}:{hs6}"):
                # Liveness beat at the start of the ranking work (C5): a slow screen
                # — or a redelivery — must not look dead to the stuck-row reaper.
                # Mirrors the stage 2/3 heartbeat (symptom B).
                heartbeat.beat(analysis.id)
                rankings = rank_and_persist(db, analysis, hs6, top_n=top_n)
                # Re-read before the transition (C5): reconcile_stuck_analyses may
                # have terminalized this row in its OWN transaction while Stage 1 ran
                # (symptom B write race). A terminal 'failed' is never overwritten by
                # a late 'ranked' — mirrors the stage 2/3 guards.
                db.refresh(analysis)
                if analysis.status == "failed":
                    log.warning(
                        "world_ranking_finished_after_terminal_status",
                        analysis_id=analysis_id,
                    )
                elif analysis.status in ("pending", "classified"):
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
            # Re-read the row before deciding the transition: the stuck-row
            # reaper may have terminalized it in its own transaction while this
            # stage ran (symptom B write race) — a terminal status is never
            # overwritten by a late completion.
            db.refresh(analysis)
            # C2 (defense-in-depth): only a ranked-or-already-enriched analysis is
            # promoted to 'enriched'. A never-ranked run ('pending'/'classified' —
            # e.g. Stage 2 enqueued before Stage 1 committed) must NOT become
            # 'enriched' with zero rankings; it is left as-is (the API precondition
            # gate is the first line of defense, this is the backstop).
            if analysis.status in ("ranked", "enriched"):
                analysis.status = "enriched"
            elif analysis.status == "failed":
                log.warning("stage2_finished_after_terminal_status", analysis_id=analysis_id)
        db.commit()
        result = {
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
    # Auto-chain Stage 3 (FREE per-market deep-dive) AFTER the commit AND OUTSIDE
    # the try (C3). Commit-before-enqueue so the Stage-3 task's own session sees the
    # enriched rows; eager mode runs it inline (tests), prod queues it. Keeping the
    # enqueue outside the try means a post-commit broker fault (a kombu/redis
    # OperationalError, which _is_transient does NOT match) can no longer be caught
    # by the except above and overwrite the just-committed 'enriched' status with
    # 'failed' (dropping Stage 3). deepen is carried forward (stays False).
    run_stage3_deepdive.delay(analysis_id, hs6, deepen=deepen)
    return result


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
            # Same terminal-status guard as stage 2 (symptom B write race).
            db.refresh(analysis)
            if analysis.status != "failed":
                analysis.status = "deepened"
            else:
                log.warning("stage3_finished_after_terminal_status", analysis_id=analysis_id)
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


@celery_app.task(name="app.workers.tasks.render_executive_report")
def render_executive_report(product_id: str) -> dict:
    """Render the Executive Multi-Market Report to object storage (no vendor calls).

    Pure Postgres read + render: builds the executive result from the persisted
    funnel/snapshot/buyer data (``build_executive_result``), renders it through
    the engine's ONE template seam (``silk_render.build_view`` →
    ``silk_reports.render_executive_docx``), and stores the ``.docx`` bytes under
    a stable per-product key. A product with zero analyses still renders — the
    engine emits a declared-gap report (I1), never a fabricated one.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from app.models import Product
    from app.services.report_view import build_executive_result
    from app.services.storage import get_storage

    with session_scope() as db:
        product = db.get(Product, uuid.UUID(product_id))
        if product is None:
            return {"error": "product not found"}
        result = build_executive_result(db, product)

    from silk_render import build_view
    from silk_reports import render_executive_docx

    view = build_view(result)
    tmp_dir = tempfile.mkdtemp(prefix="silk_exec_report_")
    try:
        path = render_executive_docx(view, str(Path(tmp_dir) / "executive.docx"))
        data = Path(path).read_bytes()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    key = f"reports/executive/{product_id}.docx"
    get_storage().put(
        key=key,
        data=data,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    return {"product_id": product_id, "report_key": key}


@celery_app.task(name="app.workers.tasks.render_research_report")
def render_research_report(product_id: str) -> dict:
    """Render the combined Top-5 DEEP-RESEARCH report to storage (ADR-0007).

    The paid, key-gated counterpart to ``render_executive_report``. Loads the
    product's persisted Top-5 ``CountryRanking`` markets and, for each, runs the
    engine's 12-mission deep research through the ONE seam
    (``engine.run_deep_research``) inside its deepen + budget scope, then composes
    the per-market findings into one combined docx stored under a stable key.

    Fail-closed (I5 / audit C3): with no ``ANTHROPIC_API_KEY`` the seam returns
    ``None`` and NO paid work runs — the task renders the declared-gap "deep
    research pending API key" document instead of fabricating a narrative, and
    marks the product ``research_status='gated'``. Idempotent, own session scope,
    terminal-state friendly (status: pending → ready | gated | failed) so the
    202-reachable trigger/poll flow always reaches a terminal state.
    """
    from app.models import Product
    from app.services import engine, research_report
    from app.services.storage import get_storage

    key = f"reports/research/{product_id}.docx"
    with session_scope() as db:
        product = db.get(Product, uuid.UUID(product_id))
        if product is None:
            return {"error": "product not found"}
        product_name = product.name_en or product.name_ar or ""
        hs_code = product.hs_code
        markets = research_report.top5_markets(db, product)
        allowed = engine.deep_research_allowed()

    # Fail-closed keyless: declared-gap "pending API key" report, ZERO paid calls.
    if not allowed:
        data = research_report.render_pending_docx(product_name, hs_code, markets)
        get_storage().put(key=key, data=data, content_type=_RESEARCH_MEDIA_TYPE)
        with session_scope() as db:
            product = db.get(Product, uuid.UUID(product_id))
            if product is not None:
                product.research_status = "gated"
                product.research_report_key = key
        log.info("research_report_gated", product_id=product_id)
        return {"product_id": product_id, "status": "gated", "report_key": key}

    # Keyed: run the engine deep research per market (each inside its own deepen +
    # budget scope, established in run_deep_research). A market that fails to
    # resolve / returns None is skipped (declared absence), never fabricated.
    try:
        per_market: list[dict] = []
        for _iso3, name in markets:
            report = engine.run_deep_research(name, product_name, hs_code)
            if report is not None:
                per_market.append(report)
        data = research_report.render_combined_docx(product_name, hs_code, per_market)
    except Exception as exc:
        log.error("research_report_failed", product_id=product_id, error=str(exc))
        with session_scope() as db:
            product = db.get(Product, uuid.UUID(product_id))
            if product is not None:
                product.research_status = "failed"
                product.failure_reason = f"deep research: {type(exc).__name__}: {exc}"[:500]
        raise

    get_storage().put(key=key, data=data, content_type=_RESEARCH_MEDIA_TYPE)
    with session_scope() as db:
        product = db.get(Product, uuid.UUID(product_id))
        if product is not None:
            product.research_status = "ready"
            product.research_report_key = key
    log.info("research_report_ready", product_id=product_id, markets=len(per_market))
    return {"product_id": product_id, "status": "ready", "report_key": key}


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
    from app.models import Campaign, Email, EmailStatus, SenderAccount
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
            # Persist WHY the send is waiting (audit 2026-08-07 C4): a blocked
            # email stays `queued` (the redispatch sweep will retry it), but the
            # row now carries the reason instead of being silently stuck.
            reason = str(exc)
            if email.status == EmailStatus.queued:
                email.blocked_reason = reason[:255]
            log.info("send_blocked", email_id=email_id, reason=reason)
            return {"email_id": email_id, "sent": False, "reason": reason}
        return {"email_id": email_id, "sent": email.status.value == "sent"}


#: Cap per hourly sweep. The beat drains any backlog across runs; the cap keeps
#: one run's memory and transaction bounded no matter how much mail history
#: accumulates.
FOLLOWUP_BATCH_LIMIT = 500


@celery_app.task(name="app.workers.tasks.process_followups")
def process_followups() -> dict:
    """Create follow-up *drafts* for sent-but-unanswered emails.

    Follow-ups are never auto-sent; they enter the same approval queue as any
    other draft. One anti-join finds sent-and-past-cutoff emails with no
    followup-1 child (previously: an unbounded full scan plus one probe query
    per candidate, over columns with no index — the hourly cost grew with all
    mail ever sent). Bounded by ``FOLLOWUP_BATCH_LIMIT`` per run.
    """
    import secrets
    from datetime import timedelta

    from sqlalchemy.orm import aliased

    from app.models import Email, EmailStatus, utcnow

    cutoff = utcnow() - timedelta(days=4)
    created = 0
    child = aliased(Email)
    with session_scope() as db:
        candidates = db.scalars(
            select(Email)
            .outerjoin(
                child,
                (child.parent_email_id == Email.id) & (child.followup_number == 1),
            )
            .where(
                child.id.is_(None),
                Email.status == EmailStatus.sent,
                Email.sent_at < cutoff,
                Email.is_followup.is_(False),
            )
            .order_by(Email.sent_at)
            .limit(FOLLOWUP_BATCH_LIMIT)
        ).all()
        from app.models import Campaign, Factory
        from app.services.email_drafting import (
            ensure_compliance_footer,
            render_html_body,
            unsubscribe_url,
        )

        for original in candidates:
            token = secrets.token_urlsafe(24)
            campaign = db.get(Campaign, original.campaign_id)
            factory = db.get(Factory, campaign.factory_id) if campaign else None
            # No factory → no sender identity / postal address to build the
            # compliance footer from. Skip rather than draft a follow-up that
            # would enter the approval queue without an unsubscribe line and with
            # mismatched text/HTML MIME parts — the exact CAN-SPAM/RFC defect the
            # footer exists to prevent. This is the rare edge (campaign or factory
            # row deleted after the original send); log it so it's observable.
            if factory is None:
                log.warning(
                    "followup_skipped_no_factory",
                    email_id=str(original.id),
                    campaign_id=str(original.campaign_id),
                )
                continue
            # Build the follow-up body exactly like an initial draft (audit L3):
            # intro + parent text, then the SAME compliance footer (sender
            # identity + postal address + unsubscribe line) keyed on THIS row's
            # own token, then render the HTML from that footed text. Previously
            # the HTML was a verbatim copy of the parent's — no intro, parent's
            # token embedded — so the two MIME parts disagreed and the follow-up
            # lacked its own unsubscribe line.
            followup_text = ensure_compliance_footer(
                _followup_body(original.body_text),
                factory,
                original.language,
                unsubscribe_url(token),
            )
            db.add(
                Email(
                    campaign_id=original.campaign_id,
                    contact_id=original.contact_id,
                    buyer_id=original.buyer_id,
                    status=EmailStatus.draft,
                    subject=f"Re: {original.subject}",
                    body_text=followup_text,
                    body_html=render_html_body(followup_text, token, original.language),
                    language=original.language,
                    is_followup=True,
                    followup_number=1,
                    parent_email_id=original.id,
                    unsubscribe_token=token,
                )
            )
            created += 1
    return {"followup_drafts_created": created}


@celery_app.task(name="app.workers.tasks.beat_heartbeat")
def beat_heartbeat() -> dict:
    """Write beat's liveness heartbeat to Redis (audit H4).

    A dead beat silently disables every reaper/sweep/warmup job; this canary
    lets /health and /metrics see beat's age so the outage is observable.
    """
    import time

    from app.observability import BEAT_HEARTBEAT_KEY, BEAT_STALE_SECONDS
    from app.redis_client import get_redis

    try:
        get_redis().set(BEAT_HEARTBEAT_KEY, repr(time.time()), ex=BEAT_STALE_SECONDS * 4)
    except Exception as exc:  # noqa: BLE001 — never let the canary crash beat
        log.warning("beat_heartbeat_write_failed", error=str(exc))
        return {"heartbeat": False}
    return {"heartbeat": True}


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


def _fail_analysis_if_unranked(analysis_id: str, reason: str) -> None:
    """Terminalize a coverage-waiting analysis — never demote a completed one.

    The bound sync may race a concurrent re-rank (or a duplicate sync); a row
    that already reached ``ranked``/``enriched``/``deepened`` must keep its
    result, so only the still-waiting states are failed.
    """
    from app.models import Analysis

    with session_scope() as db:
        analysis = db.get(Analysis, uuid.UUID(analysis_id))
        if analysis is not None and analysis.status in ("pending", "classified"):
            analysis.status = "failed"
            analysis.failure_reason = reason[:500]


@celery_app.task(name="app.workers.tasks.sync_world_trade")
def sync_world_trade(
    hs6: str,
    analysis_id: str | None = None,
    top_n: int | None = None,
    deepen: bool = False,
) -> dict:
    """Refresh ``world_trade`` Stage-1 coverage for one HS6 from UN Comtrade.

    Fail-closed (the PR #83 pattern): the live bulk download runs only when a real
    ``COMTRADE_API_KEY`` is configured and offline mode is off. Otherwise it does
    NOT fabricate coverage — it records that live data is unavailable and returns,
    so an offline/demo deployment never presents synthesized data as a real world
    screen. The heavy pandas + comtradeapicall download lives in ``etl`` (I7);
    this task is the product-side trigger that invokes it.

    When ``analysis_id`` is bound (a world ranking is waiting on this coverage),
    the task closes the loop instead of leaving the user to retry manually:
    rows written → re-dispatch :func:`run_world_ranking` (``after_sync=True``,
    one cycle only); nothing written / sync failed / source unavailable → the
    waiting analysis is terminalized with a truthful reason (I1 — no false
    «retry in a few minutes» promise, no fabricated screen).
    """
    from app.config import get_settings
    from app.services import heartbeat

    settings = get_settings()
    code = (hs6 or "").strip()
    if not code:
        return {"hs6": hs6, "synced": False, "reason": "empty hs6"}
    if settings.comtrade_offline or not settings.comtrade_api_key:
        log.warning("world_trade_sync_unavailable", hs6=code, reason="no live comtrade key")
        if analysis_id:
            _fail_analysis_if_unranked(
                analysis_id,
                f"World-market screening is unavailable for HS {code}: no live "
                "trade-data source is connected. Operator: set COMTRADE_API_KEY "
                "(UN Comtrade) to enable real world-trade coverage.",
            )
        return {"hs6": code, "synced": False, "reason": "live comtrade unavailable"}
    try:
        from etl import world_trade_sync

        if analysis_id:
            # Liveness for the analysis waiting on this sync: the bulk download
            # can take minutes, and the stuck-row reaper must not terminalize
            # the held ``pending`` row mid-sync.
            heartbeat.beat(uuid.UUID(analysis_id))
        written = world_trade_sync.run(code)
    except ImportError as exc:
        # The heavy bulk download lives in the ``etl`` environment (pandas +
        # comtradeapicall, I7). If that environment is not present, degrade
        # loudly rather than fabricate coverage.
        log.error("world_trade_sync_env_missing", hs6=code, error=str(exc))
        if analysis_id:
            _fail_analysis_if_unranked(
                analysis_id,
                f"The live coverage sync for HS {code} could not run on this "
                "deployment (etl environment unavailable); please contact the "
                "operator.",
            )
        return {"hs6": code, "synced": False, "reason": "etl environment unavailable"}
    except Exception as exc:  # noqa: BLE001 — a failed sync is a declared gap, not a crash
        log.error("world_trade_sync_failed", hs6=code, error=str(exc))
        if analysis_id:
            _fail_analysis_if_unranked(
                analysis_id,
                f"The live coverage sync for HS {code} failed "
                f"({type(exc).__name__}); please re-run the world screen.",
            )
        return {"hs6": code, "synced": False, "reason": str(exc)}
    log.info("world_trade_synced", hs6=code, rows=written)
    if analysis_id:
        if written > 0:
            # Coverage landed — complete the waiting funnel run automatically.
            # after_sync=True bounds the chain to one cycle (no sync loops).
            run_world_ranking.delay(
                analysis_id, code, top_n=top_n, deepen=deepen, after_sync=True
            )
            return {"hs6": code, "synced": True, "rows": written, "reranked": True}
        _fail_analysis_if_unranked(
            analysis_id,
            f"The live Comtrade sync completed but produced no world-trade rows "
            f"for HS {code} — the world may not report this code. Check the HS "
            "code (or re-run the screen later); no figures are invented.",
        )
    return {"hs6": code, "synced": True, "rows": written}


#: Max Comtrade sync dispatches per daily sweep (security review 2026-08-08,
#: finding 2.1) — bounds the burst a pile of newly committed codes can cause;
#: later sweeps drain the remainder. Comtrade syncs sit outside
#: SILK_PAID_DAILY_CAP, so this is their only fan-out bound.
WORLD_TRADE_SWEEP_LIMIT = 50


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
        # Committed codes — human-confirmed OR strict-auto (ADR-0009): both drive
        # the world funnel, so both deserve fresh world-trade coverage.
        confirmed_hs6 = set(
            db.scalars(
                select(func.distinct(Product.hs_code)).where(
                    Product.hs_code.is_not(None),
                    Product.hs_confirmed_by_user.is_(True) | Product.hs_auto_classified.is_(True),
                )
            ).all()
        )
        # Security review 2026-08-08 (finding 2.1): the fan-out is capped per
        # sweep — auto-classified codes now enter this set with zero human
        # action (ADR-0009), so an account adding many distinct codes must not
        # translate into an unbounded burst of Comtrade syncs. The daily beat
        # catches the remainder on subsequent sweeps (staleness cutoff keeps
        # already-fresh codes out), and the skip is DECLARED, never silent.
        for hs6 in sorted(confirmed_hs6):
            if requested >= WORLD_TRADE_SWEEP_LIMIT:
                log.warning(
                    "world_trade_refresh_capped",
                    limit=WORLD_TRADE_SWEEP_LIMIT,
                    remaining=len(confirmed_hs6) - requested,
                )
                break
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


#: Cap per redispatch sweep — bounds one run's fan-out; the beat drains any
#: larger backlog across successive runs.
REDISPATCH_BATCH_LIMIT = 200


@celery_app.task(name="app.workers.tasks.redispatch_queued_emails")
def redispatch_queued_emails() -> dict:
    """Drain the ``queued`` backlog — every non-terminal email has an owner (C4).

    Before this sweep, a worker-side ``SendBlocked`` (daily cap reached, mailbox
    disconnected, transient provider rejection) stranded an approved email in
    ``queued`` forever: the only dispatch site was the queue route, and nothing
    ever retried. Now:

    - every email still ``queued`` after ``email_redispatch_minutes`` is
      re-enqueued through the guarded send path (safe: the two-phase claim and
      the worker re-checks make redelivery at-most-once, and a still-blocked
      send just refreshes ``blocked_reason`` and waits for the next sweep);
    - a campaign with mail stuck longer than ``email_stuck_notify_hours`` gets
      ONE operator notification (deduplicated on an unread notification of the
      same kind for the same campaign), so a persistent block is a visible
      incident instead of a silent one.
    """
    from datetime import timedelta

    from app.config import get_settings
    from app.models import Campaign, Email, EmailStatus, Notification, utcnow
    from app.services import notifications

    settings = get_settings()
    now = utcnow()
    redispatch_cutoff = now - timedelta(minutes=settings.email_redispatch_minutes)
    stuck_cutoff = now - timedelta(hours=settings.email_stuck_notify_hours)
    redispatched = 0
    notified = 0
    with session_scope() as db:
        rows = db.scalars(
            select(Email)
            .where(
                Email.status == EmailStatus.queued,
                Email.queued_at.is_not(None),
                Email.queued_at < redispatch_cutoff,
            )
            .order_by(Email.queued_at)
            .limit(REDISPATCH_BATCH_LIMIT)
        ).all()
        stuck_campaigns: dict[uuid.UUID, int] = {}
        for email in rows:
            send_approved_email.delay(str(email.id))
            redispatched += 1
            if email.queued_at is not None and email.queued_at < stuck_cutoff:
                stuck_campaigns[email.campaign_id] = stuck_campaigns.get(email.campaign_id, 0) + 1
        for campaign_id, count in stuck_campaigns.items():
            campaign = db.get(Campaign, campaign_id)
            if campaign is None:
                continue
            already = db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.factory_id == campaign.factory_id,
                    Notification.kind == "sends_stuck_queued",
                    Notification.entity_id == str(campaign_id),
                    Notification.read_at.is_(None),
                )
            )
            if already:
                continue
            notifications.notify(
                db,
                factory_id=campaign.factory_id,
                kind="sends_stuck_queued",
                title="Approved emails are waiting to send",
                body=(
                    f"{count} approved email(s) in campaign '{campaign.name}' have "
                    f"been waiting more than {settings.email_stuck_notify_hours} "
                    "hours. Check the sending mailbox, its daily limit, and the "
                    "campaign status."
                ),
                entity_type="campaign",
                entity_id=str(campaign_id),
            )
            notified += 1
    if redispatched:
        log.info("queued_emails_redispatched", count=redispatched, notified=notified)
    return {"redispatched": redispatched, "campaigns_notified": notified}


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


@celery_app.task(name="app.workers.tasks.reconcile_stuck_products")
def reconcile_stuck_products() -> dict:
    """Fail products stuck in ``classification_status='pending'`` past the window.

    The intake task marks its own failures, but a worker lost to OOM/SIGKILL dies
    before ``_mark_product_failed`` runs, leaving the product ``pending`` forever
    while the UI polls. Mirror of ``reconcile_stuck_analyses`` for the products
    table, sharing the same staleness window.
    """
    from datetime import timedelta

    from app.config import get_settings
    from app.models import Product, utcnow

    settings = get_settings()
    cutoff = utcnow() - timedelta(minutes=settings.analysis_stuck_minutes)
    failed = 0
    with session_scope() as db:
        stuck = db.scalars(
            select(Product).where(
                Product.classification_status == "pending",
                Product.updated_at < cutoff,
            )
        ).all()
        for product in stuck:
            product.classification_status = "failed"
            product.failure_reason = (
                f"stalled in 'pending' for over "
                f"{settings.analysis_stuck_minutes} min (worker lost); please retry"
            )
            failed += 1
    if failed:
        log.warning("stuck_products_reconciled", count=failed)
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

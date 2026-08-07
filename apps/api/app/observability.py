"""Operational floor: dependency health checks and Prometheus request metrics.

/health used to be a static 200 — a dead database, an unreachable broker, or a
misconfigured object store all reported "ok", so platform healthchecks and
uptime monitors could not see an outage. Each check here returns ``None`` when
healthy or a short error string, and the endpoint degrades to 503 so the
orchestrator actually notices.

Checks are bounded (1s socket timeouts on Redis; a single ``SELECT 1`` on the
pooled engine; one probe write / head_bucket on storage) so a healthy path stays
fast and a blip cannot hang the healthcheck itself. Nothing here calls a paid
vendor API — storage checks talk only to our own disk/MinIO/S3.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings, get_settings
from app.logging import get_logger

log = get_logger(__name__)


def check_database() -> str | None:
    """One ``SELECT 1`` on the pooled engine; pool_pre_ping recycles dead conns."""
    try:
        from sqlalchemy import text

        from app.db import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return None
    except Exception as exc:  # noqa: BLE001 — the reason is the payload
        return f"{type(exc).__name__}: {exc}"


def check_redis(settings: Settings | None = None) -> str | None:
    """Ping the broker Redis with tight timeouts so a blip cannot hang /health."""
    settings = settings or get_settings()
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        try:
            client.ping()
        finally:
            client.close()
        return None
    except Exception as exc:  # noqa: BLE001 — the reason is the payload
        return f"{type(exc).__name__}: {exc}"


def check_storage(settings: Settings | None = None) -> str | None:
    """Exercise the configured object store (our own infra, never a paid API)."""
    settings = settings or get_settings()
    try:
        from app.services.storage import get_storage

        get_storage(settings).health_check()
        return None
    except Exception as exc:  # noqa: BLE001 — the reason is the payload
        return f"{type(exc).__name__}: {exc}"


def check_beat(settings: Settings | None = None) -> str | None:
    """Beat liveness: None when fresh, a reason when stale/never-seen.

    Kept OUT of the hard dependency set below on purpose — the API can serve
    requests while beat is down — but surfaced in /health so an operator sees a
    dead scheduler (which would freeze every reaper/sweep) instead of guessing.
    """
    age = beat_heartbeat_age(settings)
    if age is None:
        return "beat heartbeat not seen yet"
    if age > BEAT_STALE_SECONDS:
        return f"beat heartbeat stale ({int(age)}s)"
    return None


def run_health_checks(settings: Settings | None = None) -> dict[str, str]:
    """All checks as a name → "ok"|error map, for /health to render."""
    settings = settings or get_settings()
    return {
        "database": check_database() or "ok",
        "redis": check_redis(settings) or "ok",
        "storage": check_storage(settings) or "ok",
    }


REQUEST_COUNT = Counter(
    "silk_http_requests_total",
    "HTTP requests by method, route template and status.",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "silk_http_request_seconds",
    "HTTP request latency by method and route template.",
    ["method", "path"],
)


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """Count/time every request by route *template* (bounded label cardinality)."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # The router sets scope["route"] during call_next; unmatched paths
            # (404 scans, typos) collapse into one label to keep cardinality flat.
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            REQUEST_COUNT.labels(request.method, path, str(status)).inc()
            REQUEST_LATENCY.labels(request.method, path).observe(time.perf_counter() - started)


# Operational gauges the audit found missing (H4): without these an operator
# cannot answer "is the pipeline stuck?" or "did beat die?" without shelling
# into logs. They are refreshed lazily on each /metrics scrape (below) and the
# beat-liveness age also feeds /health.
QUEUE_DEPTH = Gauge(
    "silk_email_queue_depth",
    "Emails currently in a given non-terminal status.",
    ["status"],
)
STUCK_ROWS = Gauge(
    "silk_stuck_rows",
    "Rows a reaper would consider stuck (non-terminal past their SLA).",
    ["kind"],
)
BEAT_HEARTBEAT_AGE = Gauge(
    "silk_beat_heartbeat_age_seconds",
    "Seconds since Celery beat last ticked (−1 if never seen).",
)

#: Redis key beat refreshes every tick; /health + /metrics read its age.
BEAT_HEARTBEAT_KEY = "silk:beat:heartbeat"
#: Beat is considered dead if its heartbeat is older than this (beat ticks are
#: sub-minute; 300s tolerates a slow tick without false alarms).
BEAT_STALE_SECONDS = 300


def beat_heartbeat_age(settings: Settings | None = None) -> float | None:
    """Seconds since beat last ticked, or None if the heartbeat was never set."""
    from app.redis_client import get_redis

    try:
        raw = get_redis().get(BEAT_HEARTBEAT_KEY)
    except Exception:  # noqa: BLE001 — a Redis blip must not crash /health
        return None
    if raw is None:
        return None
    try:
        import time as _t

        return max(0.0, _t.time() - float(raw))
    except (TypeError, ValueError):
        return None


def _refresh_operational_gauges(settings: Settings) -> None:
    """Populate the queue/stuck/beat gauges from the DB + Redis for a scrape."""
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Analysis, Email, EmailStatus, Product

    age = beat_heartbeat_age(settings)
    BEAT_HEARTBEAT_AGE.set(age if age is not None else -1.0)
    try:
        with SessionLocal() as db:
            rows = db.execute(
                select(Email.status, func.count())
                .where(Email.status.in_([EmailStatus.queued, EmailStatus.sending]))
                .group_by(Email.status)
            ).all()
            depths = {s.value: n for s, n in rows}
            for st in ("queued", "sending"):
                QUEUE_DEPTH.labels(st).set(depths.get(st, 0))
            stuck_analyses = db.scalar(
                select(func.count()).select_from(Analysis).where(Analysis.status == "pending")
            )
            stuck_products = db.scalar(
                select(func.count())
                .select_from(Product)
                .where(Product.classification_status == "pending")
            )
            STUCK_ROWS.labels("analysis_pending").set(stuck_analyses or 0)
            STUCK_ROWS.labels("product_pending").set(stuck_products or 0)
    except Exception as exc:  # noqa: BLE001 — metrics must never 500 the scrape
        log.warning("operational_gauge_refresh_failed", error=str(exc))


def metrics_response(settings: Settings | None = None) -> Response:
    _refresh_operational_gauges(settings or get_settings())
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

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
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
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


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

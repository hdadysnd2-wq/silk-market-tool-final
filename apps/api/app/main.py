"""FastAPI application factory."""

from __future__ import annotations

import hmac

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin,
    analyses,
    auth,
    buyers,
    campaigns,
    factories,
    markets,
    notifications,
    pricing,
    products,
    public,
    reports,
    sender_accounts,
    webhooks,
)
from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.observability import (
    RequestMetricsMiddleware,
    check_beat,
    metrics_response,
    run_health_checks,
)
from app.providers.registry import active_provider_summary

log = get_logger(__name__)

API_PREFIX = "/api/v1"

DESCRIPTION = """
AI-powered export intelligence for Saudi manufacturers.

Find international buyers for a product, review AI-drafted outreach, and — only
after explicit human approval — send through deliverability-optimized cold-email
infrastructure. Every vendor sits behind a provider abstraction, so the whole
platform runs with mock adapters when no API keys are configured.
"""


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    # /docs + the OpenAPI dump are dev/staging conveniences: in production they
    # hand an attacker the full route map for free (audit: gate /docs in prod).
    is_local = settings.environment.strip().lower() == "local"
    app = FastAPI(
        title="Silk Export Intelligence API",
        version="0.1.0",
        description=DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json" if is_local else None,
        docs_url="/docs" if is_local else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestMetricsMiddleware)

    for module in (
        auth,
        factories,
        products,
        analyses,
        markets,
        buyers,
        campaigns,
        sender_accounts,
        notifications,
        pricing,
        reports,
        webhooks,
        admin,
    ):
        app.include_router(module.router, prefix=API_PREFIX)
    # Public unsubscribe lives at the root, not under the API prefix or auth.
    app.include_router(public.router)

    @app.get("/health", tags=["meta"])
    def health() -> Response:
        """Real readiness: DB + Redis + storage, 503 when any dependency is down."""
        checks = run_health_checks(settings)
        healthy = all(v == "ok" for v in checks.values())
        # Beat liveness is informational, not a hard dependency — the API serves
        # fine while beat is down, but an operator must be able to SEE a dead
        # scheduler (it freezes every reaper/sweep). Reported, never 503 (H4).
        body = {
            "status": "ok" if healthy else "degraded",
            "environment": settings.environment,
            "providers": active_provider_summary(),
            "checks": checks,
            "beat": check_beat(settings) or "ok",
        }
        return JSONResponse(body, status_code=200 if healthy else 503)

    @app.get("/metrics", tags=["meta"])
    def metrics(request: Request) -> Response:
        # Unauthenticated route-level traffic/latency intel is free recon
        # (audit L1/H4): outside local, scraping requires the METRICS_TOKEN
        # bearer. No token configured → the endpoint does not exist (404),
        # never an open default.
        if settings.environment.strip().lower() != "local":
            expected = settings.metrics_token
            supplied = request.headers.get("Authorization", "")
            # Constant-time compare so the token can't be recovered byte-by-byte
            # from response timing (matches the webhook HMAC path).
            if not expected or not hmac.compare_digest(supplied, f"Bearer {expected}"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
        return metrics_response(settings)

    log.info("app_started", providers=active_provider_summary())
    return app


app = create_app()

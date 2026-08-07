"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Response
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
from app.observability import RequestMetricsMiddleware, metrics_response, run_health_checks
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

    app = FastAPI(
        title="Silk Export Intelligence API",
        version="0.1.0",
        description=DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
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
        body = {
            "status": "ok" if healthy else "degraded",
            "environment": settings.environment,
            "providers": active_provider_summary(),
            "checks": checks,
        }
        return JSONResponse(body, status_code=200 if healthy else 503)

    @app.get("/metrics", tags=["meta"])
    def metrics() -> Response:
        return metrics_response()

    log.info("app_started", providers=active_provider_summary())
    return app


app = create_app()

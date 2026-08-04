"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    def health() -> dict:
        return {
            "status": "ok",
            "environment": settings.environment,
            "providers": active_provider_summary(),
        }

    log.info("app_started", providers=active_provider_summary())
    return app


app = create_app()

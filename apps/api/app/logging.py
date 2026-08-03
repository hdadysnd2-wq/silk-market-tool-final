"""Structured logging and (optional) Sentry wiring."""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.environment == "local":
        processors.append(structlog.dev.ConsoleRenderer(colors=False))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment)
        except ImportError:  # pragma: no cover - optional dependency
            structlog.get_logger(__name__).warning("sentry_dsn_set_but_sdk_missing")

    _configured = True


def get_logger(name: str = "silk") -> structlog.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)

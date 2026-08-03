"""Celery application and beat schedule.

In tests ``task_always_eager`` is set so tasks run inline in the calling process
against the test database, which keeps the approval/suppression suites simple and
deterministic.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

# When no worker is running (local demo, single-process deployments, tests) set
# CELERY_TASK_ALWAYS_EAGER=1 so .delay() executes the task inline in the caller.
_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "0") == "1"

celery_app = Celery(
    "silk",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=_EAGER,
    task_eager_propagates=_EAGER,
)

celery_app.conf.beat_schedule = {
    "process-followups-hourly": {
        "task": "app.workers.tasks.process_followups",
        "schedule": crontab(minute=0),
    },
    "evaluate-deliverability-hourly": {
        "task": "app.workers.tasks.evaluate_deliverability",
        "schedule": crontab(minute=15),
    },
    "reset-daily-counters": {
        "task": "app.workers.tasks.reset_daily_counters",
        "schedule": crontab(hour=0, minute=0),
    },
    "advance-warmup-daily": {
        "task": "app.workers.tasks.advance_warmup",
        "schedule": crontab(hour=0, minute=5),
    },
    "advance-sender-warmup-daily": {
        "task": "app.workers.tasks.advance_sender_warmup",
        "schedule": crontab(hour=0, minute=10),
    },
    "poll-replies": {
        "task": "app.workers.tasks.poll_replies",
        "schedule": crontab(minute="*/15"),
    },
}

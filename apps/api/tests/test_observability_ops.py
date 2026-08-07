"""Locks for the operational observability floor (audit 2026-08-07 H4).

Queue-depth + stuck-row gauges and a beat-liveness canary, so an operator can
answer "is the pipeline stuck?" / "did beat die?" without shelling into logs.
"""

from __future__ import annotations

import time

from app.observability import (
    BEAT_HEARTBEAT_KEY,
    BEAT_STALE_SECONDS,
    beat_heartbeat_age,
    check_beat,
    metrics_response,
)
from app.redis_client import get_redis


def test_beat_heartbeat_absent_is_reported(monkeypatch):
    get_redis().delete(BEAT_HEARTBEAT_KEY)
    assert beat_heartbeat_age() is None
    assert "not seen" in (check_beat() or "")


def test_beat_heartbeat_fresh_is_ok():
    get_redis().set(BEAT_HEARTBEAT_KEY, repr(time.time()))
    age = beat_heartbeat_age()
    assert age is not None and age < 5
    assert check_beat() is None


def test_beat_heartbeat_stale_is_flagged():
    stale = time.time() - (BEAT_STALE_SECONDS + 60)
    get_redis().set(BEAT_HEARTBEAT_KEY, repr(stale))
    assert "stale" in (check_beat() or "")


def test_beat_task_writes_heartbeat():
    get_redis().delete(BEAT_HEARTBEAT_KEY)
    from app.workers import tasks

    assert tasks.beat_heartbeat.apply().result == {"heartbeat": True}
    assert beat_heartbeat_age() is not None


def test_metrics_exposes_queue_and_beat_gauges(db):
    get_redis().set(BEAT_HEARTBEAT_KEY, repr(time.time()))
    body = metrics_response().body.decode()
    assert "silk_email_queue_depth" in body
    assert "silk_stuck_rows" in body
    assert "silk_beat_heartbeat_age_seconds" in body


def test_health_reports_beat_field(client):
    get_redis().set(BEAT_HEARTBEAT_KEY, repr(time.time()))
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    assert "beat" in resp.json()

"""Regression locks: Redis-backed rate limiting (Wave 2 item 6).

The old limiter was per-process memory: every quota multiplied by the number of
workers and reset on deploy. Hits now live in a Redis sorted set shared across
workers, with the in-process deque kept as the availability floor when Redis is
unreachable.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.redis_client import get_redis
from app.services import rate_limit


def test_limit_enforced_through_redis():
    for _ in range(3):
        rate_limit.check("t:redis", limit=3, window_seconds=60)
    with pytest.raises(HTTPException) as exc:
        rate_limit.check("t:redis", limit=3, window_seconds=60)
    assert exc.value.status_code == 429
    # The hits are actually in Redis (shared state), not process memory.
    assert get_redis().zcard("rl:t:redis") == 3


def test_rejected_attempt_is_not_recorded():
    for _ in range(2):
        rate_limit.check("t:norecord", limit=2, window_seconds=60)
    for _ in range(3):
        with pytest.raises(HTTPException):
            rate_limit.check("t:norecord", limit=2, window_seconds=60)
    assert get_redis().zcard("rl:t:norecord") == 2


def test_reset_clears_shared_state():
    rate_limit.check("t:reset", limit=1, window_seconds=60)
    rate_limit.reset()
    rate_limit.check("t:reset", limit=1, window_seconds=60)  # would 429 if stale


def test_falls_back_to_local_buckets_when_redis_is_down(monkeypatch):
    def _boom(*a, **k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(rate_limit, "_hit_redis", _boom)
    for _ in range(2):
        rate_limit.check("t:fallback", limit=2, window_seconds=60)
    with pytest.raises(HTTPException) as exc:
        rate_limit.check("t:fallback", limit=2, window_seconds=60)
    assert exc.value.status_code == 429

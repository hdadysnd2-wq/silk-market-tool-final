"""Shared Redis client for cross-worker state (rate limits, session denylist).

Redis is already a production dependency (Celery broker/backend); this exposes
one cached client for application-level state. Timeouts are tight (1s) so a
Redis blip degrades the calling feature instead of hanging requests — each
caller decides its own failure posture (rate limiting falls back to in-process
buckets; revocation checks fail open behind the per-request DB is_active gate).
"""

from __future__ import annotations

from functools import lru_cache

import redis

from app.config import get_settings

#: Errors that mean "Redis unreachable/broken", not "caller bug".
REDIS_ERRORS = (redis.exceptions.RedisError, OSError)


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )

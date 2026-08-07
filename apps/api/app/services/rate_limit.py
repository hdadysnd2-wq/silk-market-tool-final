"""A Redis-backed sliding-window rate limiter with an in-process fallback.

The original limiter was per-process memory only, which multiplied every quota
by the number of workers/replicas and reset it on each deploy — fine for
blunting bursts in dev, useless as a real cross-worker limit. Hits are now
recorded in a Redis sorted set per key (score = wall-clock time), so all
workers share one window.

Failure posture: if Redis is unreachable the limiter logs and falls back to the
old in-process deque — for auth throttles, availability beats strictness, and
per-worker limiting is the floor we always had. Call sites are unchanged:
``check(key, limit=..., window_seconds=...)`` raises 429 when over.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException, status

from app.logging import get_logger
from app.redis_client import REDIS_ERRORS, get_redis

log = get_logger(__name__)

_PREFIX = "rl:"

# key -> monotonic timestamps of recent hits within the window (fallback only)
_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def _hit_redis(key: str, limit: int, window_seconds: float) -> bool:
    """Record a hit in the shared window; True if allowed. Raises on Redis errors."""
    rkey = _PREFIX + key
    now = time.time()
    client = get_redis()
    pipe = client.pipeline()
    pipe.zremrangebyscore(rkey, 0, now - window_seconds)
    pipe.zcard(rkey)
    _, count = pipe.execute()
    if count >= limit:
        return False
    # Matches the in-process semantics: a rejected attempt is not recorded.
    pipe = client.pipeline()
    pipe.zadd(rkey, {uuid.uuid4().hex: now})
    pipe.expire(rkey, int(window_seconds) + 1)
    pipe.execute()
    return True


def _hit_local(key: str, limit: int, window_seconds: float) -> bool:
    now = time.monotonic()
    cutoff = now - window_seconds
    bucket = _BUCKETS[key]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def check(key: str, *, limit: int, window_seconds: float) -> None:
    """Record one hit for ``key`` and raise 429 if it exceeds ``limit`` per window."""
    try:
        allowed = _hit_redis(key, limit, window_seconds)
    except REDIS_ERRORS as exc:
        log.warning("rate_limit_redis_unavailable", key=key, error=str(exc))
        allowed = _hit_local(key, limit, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait and try again.",
        )


def reset() -> None:
    """Clear all buckets (both stores) — used by tests to isolate cases."""
    _BUCKETS.clear()
    try:
        client = get_redis()
        keys = list(client.scan_iter(match=_PREFIX + "*", count=1000))
        if keys:
            client.delete(*keys)
    except REDIS_ERRORS:
        pass

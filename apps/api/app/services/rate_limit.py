"""A minimal in-process sliding-window rate limiter.

Deliberately dependency-free (no Redis) so it works in unit tests and single-process
dev without extra wiring. Per-worker state is acceptable here: the endpoints that use
it (password change, and similar per-account throttles) only need to blunt abusive
bursts, not enforce a globally exact quota. For a hard, cross-worker limit, back this
with Redis later — the call sites stay the same.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

# key -> monotonic timestamps of recent hits within the window
_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def check(key: str, *, limit: int, window_seconds: float) -> None:
    """Record one hit for ``key`` and raise 429 if it exceeds ``limit`` per window."""
    now = time.monotonic()
    cutoff = now - window_seconds
    bucket = _BUCKETS[key]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait and try again.",
        )
    bucket.append(now)


def reset() -> None:
    """Clear all buckets — used by tests to isolate cases."""
    _BUCKETS.clear()

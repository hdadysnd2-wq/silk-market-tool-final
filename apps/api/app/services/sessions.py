"""Server-side session revocation via a Redis jti denylist.

Access tokens are 12h JWTs; before this, logout only cleared the browser
cookie, so a stolen token stayed valid until expiry with no server-side kill
switch short of deactivating the user. Every token now carries a ``jti``;
revoking stores it in Redis with a TTL equal to the token's remaining life
(the denylist cleans itself — nothing lives longer than the token it blocks).

Failure posture: ``is_revoked`` fails OPEN on a Redis blip. Closing would 401
every logged-in user whenever Redis restarts, and the per-request
``user.is_active`` DB check in ``get_current_user`` remains the hard,
Redis-independent kill switch for compromised accounts.
"""

from __future__ import annotations

import time

from app.logging import get_logger
from app.redis_client import REDIS_ERRORS, get_redis

log = get_logger(__name__)

_PREFIX = "session:revoked:"

#: Fallback TTL when a token has no exp claim (should not happen — tokens are
#: minted with one) — matches the 12h access-token lifetime.
_DEFAULT_TTL_SECONDS = 12 * 3600


def revoke(payload: dict) -> None:
    """Deny-list a decoded token's jti for the remainder of its life."""
    jti = payload.get("jti")
    if not jti:
        return  # pre-Wave-2 token: nothing to revoke; expiry bounds it
    exp = payload.get("exp")
    ttl = max(1, int(exp - time.time())) if exp else _DEFAULT_TTL_SECONDS
    try:
        get_redis().setex(_PREFIX + jti, ttl, "1")
    except REDIS_ERRORS as exc:
        # Logout must still clear the cookie; the token then rides out its TTL
        # exactly as every pre-jti token does.
        log.warning("session_revoke_unavailable", error=str(exc))


def is_revoked(jti: str | None) -> bool:
    if not jti:
        return False
    try:
        return bool(get_redis().exists(_PREFIX + jti))
    except REDIS_ERRORS as exc:
        log.warning("session_revocation_check_unavailable", error=str(exc))
        return False


def reset() -> None:
    """Clear the denylist — used by tests to isolate cases."""
    try:
        client = get_redis()
        keys = list(client.scan_iter(match=_PREFIX + "*", count=1000))
        if keys:
            client.delete(*keys)
    except REDIS_ERRORS:
        pass

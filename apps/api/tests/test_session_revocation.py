"""Regression locks: server-side session revocation (Wave 2 item 6).

Logout used to be cookie-clearing only — the 12h JWT stayed valid, so a stolen
token survived logout with no server-side kill switch short of deactivating the
user. Tokens now carry a jti; POST /auth/logout deny-lists it in Redis for the
token's remaining life, and get_current_user rejects revoked jtis.
"""

from __future__ import annotations

import time

import jwt as pyjwt

from app.config import get_settings
from app.redis_client import get_redis
from app.security import create_access_token
from app.services import sessions


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_logout_revokes_the_presented_token(client, factory_user):
    token = create_access_token(factory_user.id, factory_user.role)
    assert client.get("/api/v1/auth/me", headers=_auth(token)).status_code == 200

    resp = client.post("/api/v1/auth/logout", headers=_auth(token))
    assert resp.status_code == 204

    assert client.get("/api/v1/auth/me", headers=_auth(token)).status_code == 401


def test_logout_revokes_only_that_session(client, factory_user):
    first = create_access_token(factory_user.id, factory_user.role)
    second = create_access_token(factory_user.id, factory_user.role)

    client.post("/api/v1/auth/logout", headers=_auth(first))

    assert client.get("/api/v1/auth/me", headers=_auth(first)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_auth(second)).status_code == 200


def test_legacy_token_without_jti_still_authenticates(client, factory_user):
    # Tokens minted before the jti claim existed must keep working until they
    # expire — a deploy must not log everyone out.
    settings = get_settings()
    now = int(time.time())
    legacy = pyjwt.encode(
        {
            "sub": str(factory_user.id),
            "role": factory_user.role.value,
            "iat": now,
            "exp": now + 600,
        },
        settings.secret_key,
        algorithm="HS256",
    )
    assert client.get("/api/v1/auth/me", headers=_auth(legacy)).status_code == 200


def test_denylist_entry_expires_with_the_token(factory_user):
    token = create_access_token(factory_user.id, factory_user.role)
    payload = pyjwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    sessions.revoke(payload)

    ttl = get_redis().ttl("session:revoked:" + payload["jti"])
    remaining = payload["exp"] - time.time()
    # The denylist must clean itself: TTL tracks the token's remaining life.
    assert 0 < ttl <= remaining + 5


def test_is_revoked_fails_open_when_redis_is_down(monkeypatch):
    class _Down:
        def exists(self, *a, **k):
            raise ConnectionError("redis down")

    monkeypatch.setattr(sessions, "get_redis", lambda: _Down())
    # A Redis blip must not 401 every logged-in user; user.is_active in
    # get_current_user stays the hard kill switch.
    assert sessions.is_revoked("some-jti") is False

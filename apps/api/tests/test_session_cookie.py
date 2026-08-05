"""C2 — the backend authenticates from the httpOnly session cookie.

The browser never attaches an Authorization header (the token is httpOnly); it
sends the cookie on same-origin /api/v1 calls, and get_current_user reads it.
"""

from __future__ import annotations

from app.security import create_access_token


def test_session_cookie_authenticates(client, factory_user):
    token = create_access_token(factory_user.id, factory_user.role)
    client.cookies.set("silk_token", token)
    res = client.get("/api/v1/auth/me")  # no Authorization header
    assert res.status_code == 200, res.text
    assert res.json()["email"] == factory_user.email


def test_no_cookie_and_no_bearer_is_401(client):
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_garbage_cookie_is_401(client):
    client.cookies.set("silk_token", "not.a.jwt")
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401

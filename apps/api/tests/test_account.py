"""Self-service account endpoints: PUT /auth/me and POST /auth/change-password (A3)."""

from __future__ import annotations

from app.models import AuditLog
from app.services import rate_limit


def _register(client, email="acct@factory.com", password="Passw0rd!"):
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Old Name",
            "factory_name_ar": "مصنع",
            "factory_name_en": "Factory",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def test_update_me_changes_name_and_locale(client):
    token = _register(client)
    h = {"Authorization": f"Bearer {token}"}
    resp = client.put("/api/v1/auth/me", headers=h, json={"full_name": "New Name", "locale": "en"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "New Name"
    assert body["locale"] == "en"
    # Round-trips through GET /me.
    assert client.get("/api/v1/auth/me", headers=h).json()["full_name"] == "New Name"


def test_update_me_rejects_bad_locale(client):
    token = _register(client, email="loc@factory.com")
    h = {"Authorization": f"Bearer {token}"}
    assert client.put("/api/v1/auth/me", headers=h, json={"locale": "fr"}).status_code == 422


def test_change_password_wrong_current_rejected(client):
    rate_limit.reset()
    token = _register(client, email="cpw@factory.com")
    h = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=h,
        json={"current_password": "not-it", "new_password": "BrandNew1!"},
    )
    assert resp.status_code == 400, resp.text
    # Login with the original password still works — nothing changed.
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "cpw@factory.com", "password": "Passw0rd!"}
        ).status_code
        == 200
    )


def test_change_password_success_changes_login(client, db):
    rate_limit.reset()
    token = _register(client, email="cpw2@factory.com")
    h = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=h,
        json={"current_password": "Passw0rd!", "new_password": "BrandNew1!"},
    )
    assert resp.status_code == 204, resp.text

    # Old password no longer works; the new one does.
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "cpw2@factory.com", "password": "Passw0rd!"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "cpw2@factory.com", "password": "BrandNew1!"}
        ).status_code
        == 200
    )

    # An audit row was written, and it never carries a password.
    rows = db.query(AuditLog).filter(AuditLog.action == "user.password_changed").all()
    assert len(rows) == 1
    assert "Passw0rd" not in str(rows[0].payload)


def test_change_password_rate_limited(client):
    rate_limit.reset()
    token = _register(client, email="cpw3@factory.com")
    h = {"Authorization": f"Bearer {token}"}
    body = {"current_password": "wrong", "new_password": "BrandNew1!"}
    # 5 attempts are allowed within the window; the 6th is locked out.
    for _ in range(5):
        assert client.post("/api/v1/auth/change-password", headers=h, json=body).status_code == 400
    assert client.post("/api/v1/auth/change-password", headers=h, json=body).status_code == 429

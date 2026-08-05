"""B3 — admin user-management API (admin-only mutations, staff-readable list)."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, User, UserRole
from app.security import create_access_token, hash_password


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def _analyst(db) -> User:
    u = User(email="analyst@silk.test", password_hash=hash_password("x"), role=UserRole.analyst)
    db.add(u)
    db.commit()
    return u


def _second_admin(db, email="admin2@silk.test") -> User:
    u = User(email=email, password_hash=hash_password("x"), role=UserRole.admin)
    db.add(u)
    db.commit()
    return u


# -- authorization ---------------------------------------------------------


def test_analyst_can_list_but_not_mutate(client, db, admin_user, factory):
    analyst = _analyst(db)
    # List is staff-readable.
    assert client.get("/api/v1/admin/users", headers=_headers(analyst)).status_code == 200
    # Mutations are admin-only.
    res = client.post(
        "/api/v1/admin/users",
        headers=_headers(analyst),
        json={"email": "new@silk.co", "role": "factory_user", "factory_id": str(factory.id)},
    )
    assert res.status_code == 403, res.text


def test_factory_user_cannot_reach_admin_users(client, auth_headers):
    assert client.get("/api/v1/admin/users", headers=auth_headers).status_code == 403


# -- create ----------------------------------------------------------------


def test_create_factory_user_requires_factory(client, db, admin_user):
    res = client.post(
        "/api/v1/admin/users",
        headers=_headers(admin_user),
        json={"email": "nofac@silk.co", "role": "factory_user"},
    )
    assert res.status_code == 400, res.text


def test_create_factory_user_succeeds_without_leaking_password(client, db, admin_user, factory):
    res = client.post(
        "/api/v1/admin/users",
        headers=_headers(admin_user),
        json={"email": "fu@silk.co", "role": "factory_user", "factory_id": str(factory.id)},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["is_active"] is True
    assert body["factory_id"] == str(factory.id)
    assert "password" not in body and "password_hash" not in body

    rows = db.scalars(select(AuditLog).where(AuditLog.action == "user.created")).all()
    assert len(rows) == 1
    assert "password" not in (rows[0].payload or {})


def test_create_staff_clears_factory(client, db, admin_user, factory):
    res = client.post(
        "/api/v1/admin/users",
        headers=_headers(admin_user),
        json={"email": "an2@silk.co", "role": "analyst", "factory_id": str(factory.id)},
    )
    assert res.status_code == 201, res.text
    assert res.json()["factory_id"] is None  # staff are never tenant-scoped


def test_create_duplicate_email_conflicts(client, db, admin_user, factory):
    payload = {"email": "dup@silk.co", "role": "factory_user", "factory_id": str(factory.id)}
    h = _headers(admin_user)
    assert client.post("/api/v1/admin/users", headers=h, json=payload).status_code == 201
    assert client.post("/api/v1/admin/users", headers=h, json=payload).status_code == 409


# -- self / last-admin guards ---------------------------------------------


def test_cannot_deactivate_self(client, db, admin_user):
    res = client.post(
        f"/api/v1/admin/users/{admin_user.id}/deactivate", headers=_headers(admin_user)
    )
    assert res.status_code == 400, res.text


def test_cannot_demote_self(client, db, admin_user):
    res = client.put(
        f"/api/v1/admin/users/{admin_user.id}",
        headers=_headers(admin_user),
        json={"role": "analyst"},
    )
    assert res.status_code == 400, res.text


def test_last_active_admin_is_protected(client, db, admin_user, factory):
    # admin_user is the only admin; trying to remove that admin (self) is refused,
    # so at least one active admin always remains.
    fu = User(
        email="fu2@silk.test",
        password_hash=hash_password("x"),
        role=UserRole.factory_user,
        factory_id=factory.id,
    )
    db.add(fu)
    db.commit()
    # Deactivating a non-admin is fine (guard does not over-block).
    ok = client.post(f"/api/v1/admin/users/{fu.id}/deactivate", headers=_headers(admin_user))
    assert ok.status_code == 200, ok.text
    # But the sole admin cannot be removed.
    assert (
        client.post(
            f"/api/v1/admin/users/{admin_user.id}/deactivate", headers=_headers(admin_user)
        ).status_code
        == 400
    )


def test_second_admin_can_be_deactivated(client, db, admin_user):
    other = _second_admin(db)
    res = client.post(f"/api/v1/admin/users/{other.id}/deactivate", headers=_headers(admin_user))
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is False


# -- deactivation blocks login --------------------------------------------


def test_deactivated_user_cannot_log_in(client, db, admin_user, factory_user):
    # factory_user (conftest) logs in with "Passw0rd!".
    before = client.post(
        "/api/v1/auth/login",
        json={"email": factory_user.email, "password": "Passw0rd!"},
    )
    assert before.status_code == 200, before.text

    client.post(f"/api/v1/admin/users/{factory_user.id}/deactivate", headers=_headers(admin_user))

    after = client.post(
        "/api/v1/auth/login",
        json={"email": factory_user.email, "password": "Passw0rd!"},
    )
    assert after.status_code == 401, after.text


def test_reactivate_restores_login(client, db, admin_user, factory_user):
    client.post(f"/api/v1/admin/users/{factory_user.id}/deactivate", headers=_headers(admin_user))
    client.post(f"/api/v1/admin/users/{factory_user.id}/activate", headers=_headers(admin_user))
    res = client.post(
        "/api/v1/auth/login",
        json={"email": factory_user.email, "password": "Passw0rd!"},
    )
    assert res.status_code == 200, res.text


# -- reset password (OTP flow, never returns a code) -----------------------


def test_reset_password_is_204_and_audited(client, db, admin_user, factory_user):
    res = client.post(
        f"/api/v1/admin/users/{factory_user.id}/reset-password", headers=_headers(admin_user)
    )
    assert res.status_code == 204, res.text
    assert res.text == ""  # no body — no code leaked
    rows = db.scalars(select(AuditLog).where(AuditLog.action == "user.password_reset")).all()
    assert len(rows) == 1


# -- update ----------------------------------------------------------------


def test_update_full_name(client, db, admin_user, factory_user):
    res = client.put(
        f"/api/v1/admin/users/{factory_user.id}",
        headers=_headers(admin_user),
        json={"full_name": "Renamed User"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["full_name"] == "Renamed User"

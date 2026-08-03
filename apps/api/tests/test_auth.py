"""Authentication and role enforcement."""

from __future__ import annotations


def test_register_and_login(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@factory.com",
            "password": "Passw0rd!",
            "factory_name_ar": "مصنع",
            "factory_name_en": "Factory",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["access_token"]

    login = client.post(
        "/api/v1/auth/login", json={"email": "new@factory.com", "password": "Passw0rd!"}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "new@factory.com"
    assert me.json()["role"] == "factory_user"


def test_duplicate_registration_rejected(client):
    payload = {
        "email": "dup@factory.com",
        "password": "Passw0rd!",
        "factory_name_ar": "مصنع",
        "factory_name_en": "Factory",
    }
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert client.post("/api/v1/auth/register", json=payload).status_code == 409


def test_login_wrong_password(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "wp@factory.com",
            "password": "Passw0rd!",
            "factory_name_ar": "م",
            "factory_name_en": "F",
        },
    )
    resp = client.post("/api/v1/auth/login", json={"email": "wp@factory.com", "password": "wrong"})
    assert resp.status_code == 401


def test_otp_flow(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "otp@factory.com",
            "password": "Passw0rd!",
            "factory_name_ar": "م",
            "factory_name_en": "F",
        },
    )
    issued = client.post("/api/v1/auth/otp/request", json={"email": "otp@factory.com"})
    code = issued.json()["dev_code"]

    ok = client.post("/api/v1/auth/otp/verify", json={"email": "otp@factory.com", "code": code})
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    # Single use — the same code cannot be replayed.
    replay = client.post("/api/v1/auth/otp/verify", json={"email": "otp@factory.com", "code": code})
    assert replay.status_code == 401


def test_protected_route_requires_token(client):
    assert client.get("/api/v1/factory").status_code == 401


def test_admin_route_forbidden_for_factory_user(client, auth_headers):
    assert client.get("/api/v1/admin/factories", headers=auth_headers).status_code == 403

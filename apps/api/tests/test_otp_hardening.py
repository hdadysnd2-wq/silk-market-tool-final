"""C1 — OTP hardening (CRITICAL-1): dev-code gating, attempt cap, rate limits."""

from __future__ import annotations

from sqlalchemy import select

from app.config import get_settings
from app.models import User
from app.services import auth_service


def _register(client, email="otphard@factory.com"):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Passw0rd!",
            "factory_name_ar": "م",
            "factory_name_en": "F",
        },
    )


def test_dev_code_absent_in_non_local_env(client, monkeypatch):
    _register(client)
    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(get_settings(), "silk_dev_expose_otp", True)  # even with the flag
    res = client.post("/api/v1/auth/otp/request", json={"email": "otphard@factory.com"})
    assert res.status_code == 200
    assert "dev_code" not in res.json()


def test_dev_code_absent_local_without_flag(client, monkeypatch):
    _register(client)
    monkeypatch.setattr(get_settings(), "environment", "local")
    monkeypatch.setattr(get_settings(), "silk_dev_expose_otp", False)
    res = client.post("/api/v1/auth/otp/request", json={"email": "otphard@factory.com"})
    assert "dev_code" not in res.json()


def test_dev_code_present_only_local_with_flag(client, monkeypatch):
    _register(client)
    monkeypatch.setattr(get_settings(), "environment", "local")
    monkeypatch.setattr(get_settings(), "silk_dev_expose_otp", True)
    res = client.post("/api/v1/auth/otp/request", json={"email": "otphard@factory.com"})
    assert res.json().get("dev_code")


def test_sixth_wrong_otp_attempt_is_locked(client, db, monkeypatch):
    _register(client)
    user = db.scalar(select(User).where(User.email == "otphard@factory.com"))
    code = auth_service.issue_otp(db, user)
    db.commit()
    wrong = "000000" if code != "000000" else "111111"

    # Five wrong attempts are each rejected (and counted).
    for _ in range(5):
        r = client.post(
            "/api/v1/auth/otp/verify", json={"email": "otphard@factory.com", "code": wrong}
        )
        assert r.status_code == 401

    # The 6th attempt is locked out — even the CORRECT code no longer works.
    locked = client.post(
        "/api/v1/auth/otp/verify", json={"email": "otphard@factory.com", "code": code}
    )
    assert locked.status_code == 401


def test_otp_verify_is_rate_limited_per_account(client, monkeypatch):
    _register(client)
    # otp_verify per-account cap is 12/window; exceed it to trip a 429.
    got_429 = False
    for _ in range(15):
        r = client.post(
            "/api/v1/auth/otp/verify", json={"email": "otphard@factory.com", "code": "000000"}
        )
        if r.status_code == 429:
            got_429 = True
            break
    assert got_429


def test_login_is_rate_limited_per_account(client):
    got_429 = False
    for _ in range(12):
        r = client.post("/api/v1/auth/login", json={"email": "nobody@factory.com", "password": "x"})
        if r.status_code == 429:
            got_429 = True
            break
    assert got_429

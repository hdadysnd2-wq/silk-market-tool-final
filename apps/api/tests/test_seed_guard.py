"""C4 — the demo seed plants privileged demo accounts ONLY on ``local``.

HIGH-12: every demo account (incl. ``admin@demo.silk``) shares one well-known
password, and the API entrypoint runs this seed on every boot. Off ``local`` the
seed must create zero demo users (just reference data), so a stray
deploy/entrypoint against a shared or production DB can never plant a privileged
admin with a public credential.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.config import get_settings
from app.models import Factory, HSCode, Market, User
from app.seeds import seed


def _demo_user_count(db) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.email.like("%@demo.silk")))


def test_non_local_seed_creates_zero_demo_users(db, monkeypatch):
    """The Verify: a non-local seed plants no demo users, only reference data."""
    monkeypatch.setattr(get_settings(), "environment", "production")

    counts = seed.run()

    # Zero demo accounts anywhere — the privileged admin must not exist.
    assert _demo_user_count(db) == 0
    assert db.scalar(select(User).where(User.email == "admin@demo.silk")) is None
    assert db.scalar(select(func.count()).select_from(Factory)) == 0
    assert counts["users"] == 0 and counts["factories"] == 0
    # Reference data IS still seeded off-local.
    assert db.scalar(select(func.count()).select_from(HSCode)) > 0
    assert db.scalar(select(func.count()).select_from(Market)) > 0
    assert counts["hs_codes"] > 0 and counts["markets"] > 0


def test_non_local_seed_holds_for_staging_too(db, monkeypatch):
    """Any non-'local' value (not just 'production') gates the demo accounts."""
    monkeypatch.setattr(get_settings(), "environment", "staging")

    seed.run()

    assert _demo_user_count(db) == 0
    assert db.scalar(select(func.count()).select_from(HSCode)) > 0  # reference data seeded


def test_local_seed_creates_the_demo_admin(db, monkeypatch):
    """The gate opens on 'local': the demo admin (and factory users) exist."""
    monkeypatch.setattr(get_settings(), "environment", "local")

    counts = seed.run()

    assert db.scalar(select(User).where(User.email == "admin@demo.silk")) is not None
    assert _demo_user_count(db) > 0
    assert counts["users"] > 0 and counts["factories"] > 0

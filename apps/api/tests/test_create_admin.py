"""The production first-admin bootstrap (app.seeds.create_admin)."""

from __future__ import annotations

import pytest

from app.models import AuditLog, UserRole
from app.security import verify_password
from app.seeds.create_admin import create_or_promote_admin

PASSWORD = "operator-chosen-secret-1"  # meets MIN_PASSWORD_LENGTH


def test_creates_new_admin_with_supplied_password(db):
    user, outcome = create_or_promote_admin(db, "Owner@Example.com", "Owner", password=PASSWORD)
    assert outcome == "created"
    assert user.role == UserRole.admin
    assert user.factory_id is None
    assert user.is_active
    assert user.email == "owner@example.com"  # normalized
    assert verify_password(PASSWORD, user.password_hash)
    actions = [a.action for a in db.query(AuditLog).all()]
    assert "user.created" in actions


def test_promote_rotates_password_and_audits_previous_factory(db, factory_user):
    original_hash = factory_user.password_hash
    previous_factory_id = str(factory_user.factory_id)
    user, outcome = create_or_promote_admin(db, factory_user.email, password=PASSWORD)
    assert outcome == "promoted"
    assert user.id == factory_user.id
    assert user.role == UserRole.admin
    assert user.factory_id is None  # staff are never tenant-scoped
    # The self-chosen factory credential must not survive the promotion.
    assert user.password_hash != original_hash
    assert verify_password(PASSWORD, user.password_hash)
    rows = db.query(AuditLog).all()
    assert [r.action for r in rows] == ["user.updated"]
    assert rows[0].payload["previous_role"] == UserRole.factory_user.value
    assert rows[0].payload["previous_factory_id"] == previous_factory_id
    assert rows[0].payload["password_rotated"] is True


def test_idempotent_noop_for_existing_active_admin(db):
    created, first_outcome = create_or_promote_admin(db, "owner@example.com", password=PASSWORD)
    assert first_outcome == "created"
    original_hash = created.password_hash
    audit_rows_after_create = db.query(AuditLog).count()
    user, outcome = create_or_promote_admin(db, "owner@example.com", password=PASSWORD)
    assert outcome == "noop"
    assert user.id == created.id
    assert user.password_hash == original_hash
    # Pins the early return: a re-run writes nothing, not even an audit row.
    assert db.query(AuditLog).count() == audit_rows_after_create


def test_refuses_deactivated_account(db, factory_user):
    factory_user.is_active = False
    db.flush()
    with pytest.raises(ValueError, match="deactivated"):
        create_or_promote_admin(db, factory_user.email, password=PASSWORD)
    assert factory_user.role == UserRole.factory_user
    assert not factory_user.is_active


@pytest.mark.parametrize("bad", ["not-an-email", "owner@", "@example.com", "a@b c"])
def test_rejects_invalid_email(db, bad):
    with pytest.raises(ValueError, match="valid email"):
        create_or_promote_admin(db, bad, password=PASSWORD)


def test_rejects_short_password(db):
    with pytest.raises(ValueError, match="at least 12 characters"):
        create_or_promote_admin(db, "owner@example.com", password="short")

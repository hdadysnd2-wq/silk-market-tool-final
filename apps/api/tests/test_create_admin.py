"""The production first-admin bootstrap (app.seeds.create_admin)."""

from __future__ import annotations

import pytest

from app.models import AuditLog, UserRole
from app.security import verify_password
from app.seeds.create_admin import create_or_promote_admin


def test_creates_new_admin_with_generated_password(db):
    user, password = create_or_promote_admin(db, "Owner@Example.com", "Owner")
    db.commit()
    assert user.role == UserRole.admin
    assert user.factory_id is None
    assert user.is_active
    assert user.email == "owner@example.com"  # normalized
    assert password and len(password) >= 18
    assert verify_password(password, user.password_hash)
    actions = [a.action for a in db.query(AuditLog).all()]
    assert "user.created" in actions


def test_promotes_existing_factory_user_without_touching_password(db, factory_user):
    original_hash = factory_user.password_hash
    user, password = create_or_promote_admin(db, factory_user.email)
    db.commit()
    assert user.id == factory_user.id
    assert user.role == UserRole.admin
    assert user.factory_id is None  # staff are never tenant-scoped
    assert password is None
    assert user.password_hash == original_hash
    actions = [a.action for a in db.query(AuditLog).all()]
    assert "user.promoted_to_admin" in actions


def test_idempotent_for_existing_active_admin(db, admin_user):
    user, password = create_or_promote_admin(db, admin_user.email)
    db.commit()
    assert user.id == admin_user.id
    assert password is None


def test_rejects_invalid_email(db):
    with pytest.raises(ValueError):
        create_or_promote_admin(db, "not-an-email")

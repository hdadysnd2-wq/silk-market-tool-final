"""The audit log is append-only — UPDATE and DELETE must raise at the DB layer."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError, ProgrammingError

from app.services import audit


@pytest.fixture
def _seeded_entry(db):
    entry = audit.record(
        db, action="test_action", entity_type="test", entity_id="x", actor_label="tester"
    )
    db.commit()
    return entry


def test_audit_update_raises(db, _seeded_entry):
    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(
            text("UPDATE audit_log SET action = 'tampered' WHERE id = :id"),
            {"id": _seeded_entry.id},
        )
        db.flush()
    db.rollback()


def test_audit_delete_raises(db, _seeded_entry):
    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": _seeded_entry.id})
        db.flush()
    db.rollback()


def test_audit_insert_allowed(db):
    entry = audit.record(db, action="ok", entity_type="test", entity_id="y")
    db.commit()
    assert entry.id is not None

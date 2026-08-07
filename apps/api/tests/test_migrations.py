"""Regression locks: the migration chain is linear and matches the models.

Two migrations both numbered 0015 (PRs #84/#85 merging in parallel) broke every
deploy at `alembic upgrade head` ("Multiple head revisions are present") and
went undetected because the test schema came from create_all, never from the
chain. These tests would have caught it at PR time — and now the whole suite
runs on the migrated schema (see conftest._schema).
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.db import engine
from app.models import Base
from tests.conftest import _alembic_config

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def test_revision_ids_are_unique():
    seen: dict[str, str] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        match = re.search(
            r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", path.read_text(), re.M
        )
        assert match, f"{path.name} declares no revision id"
        rev = match.group(1)
        assert rev not in seen, f"revision {rev!r} in both {seen[rev]} and {path.name}"
        seen[rev] = path.name


def test_single_head():
    script = ScriptDirectory.from_config(_alembic_config())
    heads = script.get_heads()
    assert len(heads) == 1, f"multiple heads: {heads} — the chain must stay linear"


def _include_object(obj, name, type_, reflected, compare_to):  # noqa: ARG001
    # Documented false positive, NOT drift: this index is declared identically
    # on both sides (0001_initial renders the model's Index verbatim, DESC
    # opclass included), but alembic cannot normalize a reflected DESC
    # expression index and reports a permanent phantom add+remove.
    return not (type_ == "index" and name == "ix_product_buyer_matches_product_score")


def _drift():
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "compare_server_default": False,
                "include_object": _include_object,
            },
        )
        return compare_metadata(ctx, Base.metadata)


def test_migrated_schema_matches_models():
    """The alembic chain and Base.metadata must describe the same schema.

    Runs against the session's migrated test DB. Any diff here means a model
    changed without a migration (or vice versa) — fix the drift, do not filter
    it away (the one filtered index above is a comparator false positive, not
    drift).
    """
    diff = _drift()
    assert diff == [], f"model↔migration drift: {diff}"


def test_repair_migration_is_reentrant():
    """0018 must apply cleanly onto a DB that already has the send-claim DDL.

    downgrade to 0017 (drops only cost_per_unit) then upgrade back — the
    inspector guards must skip the already-present claimed_at/enum/CHECK. This
    is the same code path that repairs a #84-era production DB stamped '0015'.
    """
    from alembic import command

    cfg = _alembic_config()
    command.downgrade(cfg, "0017")
    command.upgrade(cfg, "head")

    assert _drift() == []

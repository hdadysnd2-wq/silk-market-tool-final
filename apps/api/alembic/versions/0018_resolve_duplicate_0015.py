"""Converge the histories left by two migrations both numbered 0015.

PRs #84 and #85 merged in parallel, each shipping a migration with
``revision = "0015"`` (products.cost_per_unit vs the two-phase-send DDL).
Alembic treats a duplicate id as ambiguous: every ``alembic upgrade head`` from
main failed with "Multiple head revisions are present" — deploys were broken at
the migrate step — and a database migrated in the #84 era is stamped '0015'
having run ONLY the cost_per_unit DDL, so the send-claim column/enum/CHECK are
missing there.

The cost_per_unit file is deleted ('0015' stays with the send-claim migration,
the one alembic's revision map already resolved), and this repair migration
applies BOTH deltas idempotently so every deployed state converges:

* fresh DB           — 0015 ran the send-claim DDL; only cost_per_unit is added.
* #84-era DB @0015   — claimed_at / 'sending' / widened CHECK are repaired;
                       the already-present cost_per_unit is skipped.
* DB at 0014 or older — full chain, then this is a near-no-op.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_CHECK = "ck_emails_sent_requires_approval"
_NEW_FAMILY = "'queued', 'sending', 'sent', 'opened', 'replied', 'bounced', 'complained'"


def _missing_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return all(c["name"] != column for c in insp.get_columns(table))


def upgrade() -> None:
    # Enum label first, committed on its own (PG forbids using a label added in
    # the same transaction); IF NOT EXISTS makes it re-entrant.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE email_status ADD VALUE IF NOT EXISTS 'sending' AFTER 'queued'")

    if _missing_column("emails", "claimed_at"):
        op.add_column("emails", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))

    if _missing_column("products", "cost_per_unit"):
        op.add_column("products", sa.Column("cost_per_unit", sa.Numeric(14, 2), nullable=True))

    # Unconditional drop+recreate is idempotent and repairs the #84-era DB whose
    # CHECK still lacks 'sending'. Family copied from 0015_send_claim_two_phase.
    op.execute(f"ALTER TABLE emails DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute(
        f"ALTER TABLE emails ADD CONSTRAINT {_CHECK} "
        f"CHECK (status NOT IN ({_NEW_FAMILY}) OR approved_at IS NOT NULL)"
    )


def downgrade() -> None:
    # This migration owns cost_per_unit now (its 0015 file is deleted); the
    # send-claim delta is owned by 0015 and left for its own downgrade.
    if not _missing_column("products", "cost_per_unit"):
        op.drop_column("products", "cost_per_unit")

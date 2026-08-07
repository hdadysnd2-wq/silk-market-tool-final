"""Two-phase send claim: ``emails.claimed_at`` + ``sending`` status.

The send worker now claims a row (status ``queued`` → ``sending``, ``claimed_at``
stamped) and COMMITs before calling the provider, so a worker crash or broker
redelivery cannot re-send. ``sending`` joins the sent-family (post-approval), so
the approval CHECK constraint is widened to include it.

The enum value is added in an autocommit block because PostgreSQL forbids using
a newly added enum label inside the same transaction that adds it — the CHECK
recreation below references ``'sending'``.

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
_OLD_FAMILY = "'queued', 'sent', 'opened', 'replied', 'bounced', 'complained'"
_NEW_FAMILY = "'queued', 'sending', 'sent', 'opened', 'replied', 'bounced', 'complained'"


def upgrade() -> None:
    # 1) Add the enum label first, committed on its own (PG restriction).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE email_status ADD VALUE IF NOT EXISTS 'sending' AFTER 'queued'")

    # 2) Claim timestamp for the pre-egress lock.
    op.add_column("emails", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))

    # 3) Widen the approval CHECK so a ``sending`` row also requires an approver.
    op.execute(f"ALTER TABLE emails DROP CONSTRAINT {_CHECK}")
    op.execute(
        f"ALTER TABLE emails ADD CONSTRAINT {_CHECK} "
        f"CHECK (status NOT IN ({_NEW_FAMILY}) OR approved_at IS NOT NULL)"
    )


def downgrade() -> None:
    # Resolve any in-flight claims before the label disappears.
    op.execute("UPDATE emails SET status = 'queued', claimed_at = NULL WHERE status = 'sending'")
    op.execute(f"ALTER TABLE emails DROP CONSTRAINT {_CHECK}")
    op.execute(
        f"ALTER TABLE emails ADD CONSTRAINT {_CHECK} "
        f"CHECK (status NOT IN ({_OLD_FAMILY}) OR approved_at IS NOT NULL)"
    )
    op.drop_column("emails", "claimed_at")
    # Note: PostgreSQL cannot DROP an enum value; 'sending' remains defined but
    # unused after downgrade, which is harmless.

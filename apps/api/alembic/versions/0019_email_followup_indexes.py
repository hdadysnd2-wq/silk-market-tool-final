"""Indexes for the hourly follow-up sweep.

``process_followups`` scans ``emails`` by ``(status, sent_at)`` and probes for
an existing child by ``parent_email_id`` — both previously unindexed, so the
hourly beat did a sequential scan of the whole table plus one more per
candidate, with cost growing monotonically with total mail ever sent.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_emails_status_sent_at", "emails", ["status", "sent_at"])
    op.create_index("ix_emails_parent_email_id", "emails", ["parent_email_id"])


def downgrade() -> None:
    op.drop_index("ix_emails_parent_email_id", table_name="emails")
    op.drop_index("ix_emails_status_sent_at", table_name="emails")

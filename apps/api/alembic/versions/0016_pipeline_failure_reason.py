"""Persisted failure reason on products + analyses (pipeline error recovery).

Pipeline tasks now transition to a terminal ``failed`` status on unrecoverable
error and record why, so the UI can explain the failure and offer retry / manual
HS entry instead of polling a stuck ``pending`` forever.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("failure_reason", sa.String(length=500), nullable=True))
    op.add_column("analyses", sa.Column("failure_reason", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "failure_reason")
    op.drop_column("products", "failure_reason")

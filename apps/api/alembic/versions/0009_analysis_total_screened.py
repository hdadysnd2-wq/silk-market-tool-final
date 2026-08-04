"""Persist the Stage-1 world-screen count on an analysis (funnel transparency).

Records how many markets were screened worldwide so the report can show the
funnel honestly ("screened N → shortlisted M → top 5") with the real world count
rather than the shortlist length. Nullable so existing rows are untouched.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("total_screened", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "total_screened")

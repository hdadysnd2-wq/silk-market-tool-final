"""Record how many markets the Stage-1 top-20% cut kept (funnel transparency).

J1 replaces the fixed top-20 shortlist with a proportional cut — ceil(20%) of
covered markets, clamped to [5, 30] — so the shortlist size now varies per HS6.
``analyses.shortlisted`` persists the kept count next to ``total_screened`` so
the report can show "screened N → shortlisted M → top 5" from stored facts.
Nullable — runs predating this column simply have no recorded value (a declared
absence, I1), never a back-filled guess.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("shortlisted", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "shortlisted")

"""Product unit cost, for margin threads (Wave 3 part 2).

The factory's own per-unit cost, used to compute the margin against a competitor's
observed price. Nullable — without it the margin stays a declared gap.

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
    op.add_column(
        "products",
        sa.Column("cost_per_unit", sa.Numeric(precision=14, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "cost_per_unit")

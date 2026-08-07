"""Real factory-supplied per-unit cost on a product (backlog: closed PR #39 idea).

``main`` computes competitor margins as *gross headroom* against the factory's
offer-price midpoint — an estimate. This nullable column lets a factory record
its **actual** per-unit production cost so ``services/margin.py`` can show a real
gross margin when it is present, falling back to the offer estimate otherwise.
Nullable so every existing row is untouched (no backfill, no default).

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("cost_per_unit", sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "cost_per_unit")

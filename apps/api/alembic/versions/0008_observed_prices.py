"""Observed competitor prices on a market snapshot (Wave 3, deepen path / I5).

Stores the paid local-price layer's observed listings per (hs_code, market):
[{competitor, price, currency, url, store, source}]. Nullable — populated only
when the deepen price fetch runs for that market.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "market_snapshots",
        sa.Column("observed_prices", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_snapshots", "observed_prices")

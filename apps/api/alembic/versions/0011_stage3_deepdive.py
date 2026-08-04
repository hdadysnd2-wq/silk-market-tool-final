"""Stage-3 per-market deep-dive column on the world-funnel country ranking.

Funnel Stage 3 runs a per-country deep-dive on the top-5 finalists using the
engine's FREE, offline capabilities (competitor snapshot, requirements checklist,
correlation threads) and persists the result per-market in ``deepdive``. Nullable
— Stage-1/Stage-2-only runs leave it empty; a finalist with no alpha-2 mapping is
a declared gap inside ``deepdive`` (I1), never a fabricated deep-dive.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "country_rankings",
        sa.Column("deepdive", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("country_rankings", "deepdive")

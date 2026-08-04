"""Stage-2 enrichment columns on the world-funnel country ranking.

Funnel Stage 2 enriches the Stage-1 shortlist with budgeted live signals (applied
tariff, PPP) and re-ranks to the top 5. ``stage2_score`` holds the re-ranking
score and ``enrichment`` the signals + provenance. Both nullable — Stage-1-only
runs leave them empty; a failed signal is a declared gap inside ``enrichment``
(I1), never a fabricated number.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("country_rankings", sa.Column("stage2_score", sa.Numeric(20, 4), nullable=True))
    op.add_column(
        "country_rankings",
        sa.Column("enrichment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("country_rankings", "enrichment")
    op.drop_column("country_rankings", "stage2_score")

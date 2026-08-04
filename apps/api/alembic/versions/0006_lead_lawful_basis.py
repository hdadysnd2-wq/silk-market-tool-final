"""Per-lead lawful basis for direct marketing (I8 / PDPL Art.25 / GDPR).

Records, on each product↔buyer match, the lawful basis that discovery established
for contacting the lead, plus a human-readable note. Nullable so existing rows are
untouched; discovery backfills every new match.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_buyer_matches",
        sa.Column("lawful_basis", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "product_buyer_matches",
        sa.Column("basis_note", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_buyer_matches", "basis_note")
    op.drop_column("product_buyer_matches", "lawful_basis")

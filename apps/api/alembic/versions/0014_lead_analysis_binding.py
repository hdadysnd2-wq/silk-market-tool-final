"""Bind lead discovery to a specific analysis (decision #6 / I8).

Adds ``product_buyer_matches.analysis_id`` so every lead fetch is stamped with
the analysis it served. Nullable: rows predating this column keep NULL, and the
FK is SET NULL so a match survives erasure of the analysis record.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_buyer_matches",
        sa.Column("analysis_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_product_buyer_matches_analysis",
        "product_buyer_matches",
        "analyses",
        ["analysis_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_product_buyer_matches_analysis_id",
        "product_buyer_matches",
        ["analysis_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_buyer_matches_analysis_id", table_name="product_buyer_matches")
    op.drop_constraint(
        "fk_product_buyer_matches_analysis", "product_buyer_matches", type_="foreignkey"
    )
    op.drop_column("product_buyer_matches", "analysis_id")

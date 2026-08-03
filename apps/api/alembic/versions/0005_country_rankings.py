"""Country rankings — the world-funnel top-5 persisted per analysis.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "country_rankings",
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("importer_iso3", sa.String(length=3), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("import_usd", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("yoy_growth", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("cagr_3y", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("screen_score", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("is_transit_hub", sa.Boolean(), nullable=False),
        sa.Column("is_mirror", sa.Boolean(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stage", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_country_rankings_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_country_rankings")),
    )
    op.create_index(
        op.f("ix_country_rankings_analysis_id"),
        "country_rankings",
        ["analysis_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_country_rankings_analysis_id"), table_name="country_rankings")
    op.drop_table("country_rankings")

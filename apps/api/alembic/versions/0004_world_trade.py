"""World-trade Stage-1 screening table (funnel Stage 1 + transit-port guard I9).

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "world_trade",
        sa.Column("hs6", sa.String(length=6), nullable=False),
        sa.Column("importer_iso3", sa.String(length=3), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("import_usd", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("import_qty", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("yoy_growth", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("cagr_3y", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("is_transit_hub", sa.Boolean(), nullable=False),
        sa.Column("is_mirror", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_trade")),
        sa.UniqueConstraint(
            "hs6", "importer_iso3", "year", name="uq_world_trade_hs6_importer_year"
        ),
    )
    op.create_index(op.f("ix_world_trade_hs6"), "world_trade", ["hs6"], unique=False)
    op.create_index(
        op.f("ix_world_trade_importer_iso3"), "world_trade", ["importer_iso3"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_world_trade_importer_iso3"), table_name="world_trade")
    op.drop_index(op.f("ix_world_trade_hs6"), table_name="world_trade")
    op.drop_table("world_trade")

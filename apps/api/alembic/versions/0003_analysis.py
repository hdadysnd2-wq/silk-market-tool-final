"""Analysis runs and engine HS classifications (Phase 1 persistence).

Adds the ``analyses`` and ``hs_classifications`` tables: an analysis run through
the Celery worker persists to Postgres with the full provenance envelope on every
proposal (decision #4 / I1), stored unconfirmed (I2).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("deepen", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_analyses_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analyses")),
    )
    op.create_index(op.f("ix_analyses_product_id"), "analyses", ["product_id"], unique=False)

    op.create_table(
        "hs_classifications",
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("proposed_code", sa.String(length=6), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("data_year", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_hs_classifications_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hs_classifications")),
    )
    op.create_index(
        op.f("ix_hs_classifications_analysis_id"),
        "hs_classifications",
        ["analysis_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_hs_classifications_analysis_id"), table_name="hs_classifications")
    op.drop_table("hs_classifications")
    op.drop_index(op.f("ix_analyses_product_id"), table_name="analyses")
    op.drop_table("analyses")

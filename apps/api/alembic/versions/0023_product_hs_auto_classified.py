"""Provenance flag for engine-committed HS codes (owner decision 2026-08-08).

``products.hs_auto_classified`` marks an ``hs_code`` committed by the engine's
strict ``tier="auto"`` gate rather than a human. ``hs_confirmed_by_user`` keeps
its exact meaning (human action only, invariant I2 as amended by ADR-0009) —
the two flags are never conflated.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "hs_auto_classified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "hs_auto_classified")

"""Deep-research (Top-5) report status + storage key on products (ADR-0007).

The paid, key-gated deep-research report (12 engine missions × Top-5 markets) is
triggered on demand and rendered by a worker task, so the product needs a
pollable terminal status like the other pipeline tasks. ``research_status``
(None → pending → ready | gated | failed) and ``research_report_key`` (the stored
docx key) carry that state. Both nullable — products predating this column simply
have never requested the report (a declared absence, I1), never a back-filled
guess.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("research_status", sa.String(length=24), nullable=True))
    op.add_column(
        "products", sa.Column("research_report_key", sa.String(length=512), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("products", "research_report_key")
    op.drop_column("products", "research_status")

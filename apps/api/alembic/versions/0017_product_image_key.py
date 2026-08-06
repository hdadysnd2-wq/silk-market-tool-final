"""Backend-agnostic image storage key on products.

The worker's vision pass now fetches image bytes by a stable storage ``key``
through the storage interface, instead of the old ``image_url`` (a ``file://``
path on the API container the worker could not read on a multi-container deploy).

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("image_key", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "image_key")

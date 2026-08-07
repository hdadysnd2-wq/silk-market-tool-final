"""Add 'importer_intel' to the buyer_source enum.

The engine's paid importer-intel agents (Volza bills of lading, Explee) are
registered as additional buyer-discovery providers (Wave 3 item 4); buyers they
surface carry their own source label so provenance stays honest — a named
importer from a paid platform is neither a customs transaction nor a Maps
listing.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New enum label, committed on its own (PG forbids using a label added in
    # the same transaction); IF NOT EXISTS makes it re-entrant.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE buyer_source ADD VALUE IF NOT EXISTS 'importer_intel'")


def downgrade() -> None:
    # PostgreSQL cannot DROP an enum value; 'importer_intel' remains defined but
    # unused after downgrade, which is harmless.
    pass

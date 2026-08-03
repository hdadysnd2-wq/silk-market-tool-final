"""Multi-tenant sender accounts, notifications, and campaign→mailbox link.

Adds the ``sender_provider_type`` and ``sender_verification_status`` enums, the
``sender_accounts`` table (per-factory connected mailboxes with encrypted OAuth
tokens and per-account send governance), the ``notifications`` table, and a
nullable ``sender_account_id`` FK on ``campaigns``.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE sender_provider_type AS ENUM ('gmail', 'microsoft', 'mock')")
    op.execute(
        "CREATE TYPE sender_verification_status AS ENUM "
        "('pending', 'verified', 'needs_reauth', 'disabled')"
    )

    op.create_table(
        'sender_accounts',
        sa.Column('factory_id', sa.Uuid(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column(
            'provider_type',
            postgresql.ENUM(
                'gmail', 'microsoft', 'mock',
                name='sender_provider_type', create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('provider_account_id', sa.String(length=128), nullable=True),
        sa.Column('display_name', sa.String(length=160), nullable=True),
        # OAuth secrets are stored encrypted (see app.crypto); never plaintext.
        sa.Column('access_token_encrypted', sa.Text(), nullable=True),
        sa.Column('refresh_token_encrypted', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scopes', sa.Text(), nullable=True),
        sa.Column(
            'verification_status',
            postgresql.ENUM(
                'pending', 'verified', 'needs_reauth', 'disabled',
                name='sender_verification_status', create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reauth_reason', sa.String(length=255), nullable=True),
        sa.Column('daily_send_limit', sa.Integer(), nullable=False),
        sa.Column('daily_sent_count', sa.Integer(), nullable=False),
        sa.Column('daily_counter_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('warmup_stage', sa.Integer(), nullable=False),
        sa.Column('warmup_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['factory_id'], ['factories.id'],
            name=op.f('fk_sender_accounts_factory_id_factories'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sender_accounts')),
        sa.UniqueConstraint('factory_id', 'email', 'provider_type', name='factory_email_provider'),
    )
    op.create_index(
        op.f('ix_sender_accounts_factory_id'), 'sender_accounts', ['factory_id'], unique=False
    )
    op.create_index(
        op.f('ix_sender_accounts_email'), 'sender_accounts', ['email'], unique=False
    )

    op.create_table(
        'notifications',
        sa.Column('factory_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('entity_type', sa.String(length=64), nullable=True),
        sa.Column('entity_id', sa.String(length=64), nullable=True),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['factory_id'], ['factories.id'],
            name=op.f('fk_notifications_factory_id_factories'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_notifications_user_id_users'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    )
    op.create_index(
        op.f('ix_notifications_factory_id'), 'notifications', ['factory_id'], unique=False
    )
    op.create_index(op.f('ix_notifications_kind'), 'notifications', ['kind'], unique=False)

    # A campaign sends from a connected mailbox; SET NULL keeps the campaign row
    # if the mailbox is later disconnected (its sends are then blocked).
    op.add_column('campaigns', sa.Column('sender_account_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f('fk_campaigns_sender_account_id_sender_accounts'),
        'campaigns', 'sender_accounts',
        ['sender_account_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_campaigns_sender_account_id'), 'campaigns', ['sender_account_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_campaigns_sender_account_id'), table_name='campaigns')
    op.drop_constraint(
        op.f('fk_campaigns_sender_account_id_sender_accounts'), 'campaigns', type_='foreignkey'
    )
    op.drop_column('campaigns', 'sender_account_id')

    op.drop_index(op.f('ix_notifications_kind'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_factory_id'), table_name='notifications')
    op.drop_table('notifications')

    op.drop_index(op.f('ix_sender_accounts_email'), table_name='sender_accounts')
    op.drop_index(op.f('ix_sender_accounts_factory_id'), table_name='sender_accounts')
    op.drop_table('sender_accounts')

    op.execute("DROP TYPE IF EXISTS sender_verification_status")
    op.execute("DROP TYPE IF EXISTS sender_provider_type")

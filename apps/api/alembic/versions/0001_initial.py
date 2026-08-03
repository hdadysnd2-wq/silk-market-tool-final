"""Initial schema.

Creates the pgvector extension, every enum type, all sixteen tables, the
``sent_requires_approval`` CHECK constraint that makes an unapproved send
impossible to persist, and the trigger that makes ``audit_log`` append-only.

Revision ID: 0001
Revises:
"""
from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector backs product embeddings (similar-product lookups).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Enum types are created once here; the columns below reference them with
    # create_type=False so a type shared by several tables is not created twice.
    op.execute(
        "CREATE TYPE user_role AS ENUM ('factory_user', 'admin', 'analyst')"
    )
    op.execute(
        "CREATE TYPE email_status AS ENUM ("
        "'draft', 'approved', 'rejected', 'queued', 'sent', 'opened', 'replied', "
        "'bounced', 'complained', 'blocked_suppressed', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE verification_status AS ENUM "
        "('unverified', 'valid', 'risky', 'invalid')"
    )
    op.execute(
        "CREATE TYPE buyer_source AS ENUM "
        "('customs', 'comtrade', 'enrichment', 'maps', 'manual')"
    )
    op.execute(
        "CREATE TYPE campaign_status AS ENUM "
        "('draft', 'active', 'paused', 'auto_paused', 'completed')"
    )
    op.execute(
        "CREATE TYPE suppression_reason AS ENUM "
        "('unsubscribe', 'bounce', 'complaint', 'manual', 'legal')"
    )

    op.create_table('factories',
    sa.Column('name_ar', sa.String(length=255), nullable=False),
    sa.Column('name_en', sa.String(length=255), nullable=False),
    sa.Column('description_ar', sa.Text(), nullable=True),
    sa.Column('description_en', sa.Text(), nullable=True),
    sa.Column('sector', sa.String(length=64), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('country_iso2', sa.String(length=2), nullable=False),
    sa.Column('website', sa.String(length=255), nullable=True),
    sa.Column('logo_url', sa.String(length=512), nullable=True),
    sa.Column('cr_number', sa.String(length=64), nullable=True),
    sa.Column('contact_person', sa.String(length=160), nullable=True),
    sa.Column('contact_email', sa.String(length=255), nullable=True),
    sa.Column('contact_phone', sa.String(length=64), nullable=True),
    sa.Column('postal_address', sa.Text(), nullable=True),
    sa.Column('sending_domain', sa.String(length=255), nullable=True),
    sa.Column('spf_ok', sa.Boolean(), nullable=False),
    sa.Column('dkim_ok', sa.Boolean(), nullable=False),
    sa.Column('dmarc_ok', sa.Boolean(), nullable=False),
    sa.Column('warmup_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('warmup_day', sa.Integer(), nullable=False),
    sa.Column('daily_send_count', sa.Integer(), nullable=False),
    sa.Column('daily_counter_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('inbox_count', sa.Integer(), nullable=False),
    sa.Column('sends_paused', sa.Boolean(), nullable=False),
    sa.Column('paused_reason', sa.String(length=255), nullable=True),
    sa.Column('onboarding_completed', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_factories'))
    )
    op.create_index(op.f('ix_factories_sector'), 'factories', ['sector'], unique=False)
    op.create_table('hs_codes',
    sa.Column('code', sa.String(length=6), nullable=False),
    sa.Column('parent_code', sa.String(length=6), nullable=True),
    sa.Column('level', sa.Integer(), nullable=False),
    sa.Column('description_en', sa.Text(), nullable=False),
    sa.Column('description_ar', sa.Text(), nullable=False),
    sa.Column('sector', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_hs_codes'))
    )
    op.create_index(op.f('ix_hs_codes_parent_code'), 'hs_codes', ['parent_code'], unique=False)
    op.create_index(op.f('ix_hs_codes_sector'), 'hs_codes', ['sector'], unique=False)
    op.create_table('market_snapshots',
    sa.Column('hs_code', sa.String(length=6), nullable=False),
    sa.Column('market_iso2', sa.String(length=2), nullable=False),
    sa.Column('total_import_usd', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('trend_pct', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('top_exporters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('yearly_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('provider_name', sa.String(length=64), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_market_snapshots')),
    sa.UniqueConstraint('hs_code', 'market_iso2', name='hs_code_market')
    )
    op.create_index(op.f('ix_market_snapshots_hs_code'), 'market_snapshots', ['hs_code'], unique=False)
    op.create_index(op.f('ix_market_snapshots_market_iso2'), 'market_snapshots', ['market_iso2'], unique=False)
    op.create_table('markets',
    sa.Column('iso2', sa.String(length=2), nullable=False),
    sa.Column('name_en', sa.String(length=120), nullable=False),
    sa.Column('name_ar', sa.String(length=120), nullable=False),
    sa.Column('region', sa.String(length=64), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('primary_language', sa.String(length=2), nullable=False),
    sa.Column('is_gcc', sa.Boolean(), nullable=False),
    sa.Column('is_eu', sa.Boolean(), nullable=False),
    sa.Column('is_us', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('iso2', name=op.f('pk_markets'))
    )
    op.create_table('buyers',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('normalized_name', sa.String(length=255), nullable=False),
    sa.Column('country_iso2', sa.String(length=2), nullable=False),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('domain', sa.String(length=255), nullable=True),
    sa.Column('website', sa.String(length=512), nullable=True),
    sa.Column('phone', sa.String(length=64), nullable=True),
    sa.Column('address', sa.String(length=512), nullable=True),
    sa.Column('industry', sa.String(length=120), nullable=True),
    sa.Column('employee_count', sa.Integer(), nullable=True),
    sa.Column('source', postgresql.ENUM('customs', 'comtrade', 'enrichment', 'maps', 'manual', name='buyer_source', create_type=False), nullable=False),
    sa.Column('provider_name', sa.String(length=64), nullable=True),
    sa.Column('source_confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('firmographics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('freshness_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('enriched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('legal_review_required', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['country_iso2'], ['markets.iso2'], name=op.f('fk_buyers_country_iso2_markets'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_buyers')),
    sa.UniqueConstraint('normalized_name', 'country_iso2', name='normalized_name_country')
    )
    op.create_index('ix_buyers_country_iso2', 'buyers', ['country_iso2'], unique=False)
    op.create_index(op.f('ix_buyers_domain'), 'buyers', ['domain'], unique=False)
    op.create_table('products',
    sa.Column('factory_id', sa.UUID(), nullable=False),
    sa.Column('name_ar', sa.String(length=255), nullable=False),
    sa.Column('name_en', sa.String(length=255), nullable=False),
    sa.Column('description_ar', sa.Text(), nullable=True),
    sa.Column('description_en', sa.Text(), nullable=True),
    sa.Column('image_url', sa.String(length=512), nullable=True),
    sa.Column('price_min', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('price_max', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('hs_code', sa.String(length=6), nullable=True),
    sa.Column('hs_candidates', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('hs_confirmed_by_user', sa.Boolean(), nullable=False),
    sa.Column('classification_status', sa.String(length=24), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=256), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['factory_id'], ['factories.id'], name=op.f('fk_products_factory_id_factories'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['hs_code'], ['hs_codes.code'], name=op.f('fk_products_hs_code_hs_codes'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products'))
    )
    op.create_index(op.f('ix_products_factory_id'), 'products', ['factory_id'], unique=False)
    op.create_index(op.f('ix_products_hs_code'), 'products', ['hs_code'], unique=False)
    op.create_table('users',
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=160), nullable=True),
    sa.Column('role', postgresql.ENUM('factory_user', 'admin', 'analyst', name='user_role', create_type=False), nullable=False),
    sa.Column('factory_id', sa.UUID(), nullable=True),
    sa.Column('locale', sa.String(length=5), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('otp_code_hash', sa.String(length=255), nullable=True),
    sa.Column('otp_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['factory_id'], ['factories.id'], name=op.f('fk_users_factory_id_factories'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_factory_id'), 'users', ['factory_id'], unique=False)
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('actor_label', sa.String(length=160), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('factory_id', sa.UUID(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_audit_log_actor_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['factory_id'], ['factories.id'], name=op.f('fk_audit_log_factory_id_factories'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_action'), 'audit_log', ['action'], unique=False)
    op.create_index(op.f('ix_audit_log_actor_user_id'), 'audit_log', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_audit_log_entity_id'), 'audit_log', ['entity_id'], unique=False)
    op.create_index(op.f('ix_audit_log_factory_id'), 'audit_log', ['factory_id'], unique=False)
    op.create_table('campaigns',
    sa.Column('factory_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('market_iso2', sa.String(length=2), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', postgresql.ENUM('draft', 'active', 'paused', 'auto_paused', 'completed', name='campaign_status', create_type=False), nullable=False),
    sa.Column('paused_reason', sa.String(length=255), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('prepared_by_staff', sa.Boolean(), nullable=False),
    sa.Column('total_emails', sa.Integer(), nullable=False),
    sa.Column('sent_count', sa.Integer(), nullable=False),
    sa.Column('opened_count', sa.Integer(), nullable=False),
    sa.Column('replied_count', sa.Integer(), nullable=False),
    sa.Column('bounced_count', sa.Integer(), nullable=False),
    sa.Column('complained_count', sa.Integer(), nullable=False),
    sa.Column('reported_meetings', sa.Integer(), nullable=False),
    sa.Column('reported_rfqs', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_campaigns_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['factory_id'], ['factories.id'], name=op.f('fk_campaigns_factory_id_factories'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_campaigns_product_id_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_campaigns'))
    )
    op.create_index(op.f('ix_campaigns_factory_id'), 'campaigns', ['factory_id'], unique=False)
    op.create_index(op.f('ix_campaigns_market_iso2'), 'campaigns', ['market_iso2'], unique=False)
    op.create_index(op.f('ix_campaigns_product_id'), 'campaigns', ['product_id'], unique=False)
    op.create_table('contacts',
    sa.Column('buyer_id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=160), nullable=True),
    sa.Column('title', sa.String(length=160), nullable=True),
    sa.Column('language', sa.String(length=2), nullable=False),
    sa.Column('verification_status', postgresql.ENUM('unverified', 'valid', 'risky', 'invalid', name='verification_status', create_type=False), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', sa.String(length=64), nullable=True),
    sa.Column('found_via', sa.String(length=64), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['buyer_id'], ['buyers.id'], name=op.f('fk_contacts_buyer_id_buyers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contacts')),
    sa.UniqueConstraint('buyer_id', 'email', name='buyer_email')
    )
    op.create_index(op.f('ix_contacts_buyer_id'), 'contacts', ['buyer_id'], unique=False)
    op.create_index(op.f('ix_contacts_email'), 'contacts', ['email'], unique=False)
    op.create_table('hs_corrections',
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('suggested_code', sa.String(length=6), nullable=True),
    sa.Column('suggested_confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('chosen_code', sa.String(length=6), nullable=False),
    sa.Column('corrected_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['corrected_by'], ['users.id'], name=op.f('fk_hs_corrections_corrected_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_hs_corrections_product_id_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hs_corrections'))
    )
    op.create_index(op.f('ix_hs_corrections_product_id'), 'hs_corrections', ['product_id'], unique=False)
    op.create_table('product_buyer_matches',
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('buyer_id', sa.UUID(), nullable=False),
    sa.Column('market_iso2', sa.String(length=2), nullable=False),
    sa.Column('relevance_score', sa.Integer(), nullable=False),
    sa.Column('score_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['buyer_id'], ['buyers.id'], name=op.f('fk_product_buyer_matches_buyer_id_buyers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_product_buyer_matches_product_id_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_product_buyer_matches')),
    sa.UniqueConstraint('product_id', 'buyer_id', name='product_buyer')
    )
    op.create_index(op.f('ix_product_buyer_matches_buyer_id'), 'product_buyer_matches', ['buyer_id'], unique=False)
    op.create_index(op.f('ix_product_buyer_matches_market_iso2'), 'product_buyer_matches', ['market_iso2'], unique=False)
    op.create_index('ix_product_buyer_matches_product_score', 'product_buyer_matches', ['product_id', 'relevance_score'], unique=False, postgresql_ops={'relevance_score': 'DESC'})
    op.create_table('shipments',
    sa.Column('buyer_id', sa.UUID(), nullable=True),
    sa.Column('raw_consignee_name', sa.String(length=255), nullable=False),
    sa.Column('raw_shipper_name', sa.String(length=255), nullable=True),
    sa.Column('hs_code', sa.String(length=6), nullable=False),
    sa.Column('origin_iso2', sa.String(length=2), nullable=False),
    sa.Column('dest_iso2', sa.String(length=2), nullable=False),
    sa.Column('shipment_date', sa.Date(), nullable=False),
    sa.Column('value_usd', sa.Numeric(precision=16, scale=2), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=16, scale=3), nullable=True),
    sa.Column('quantity_unit', sa.String(length=16), nullable=True),
    sa.Column('source', postgresql.ENUM('customs', 'comtrade', 'enrichment', 'maps', 'manual', name='buyer_source', create_type=False), nullable=False),
    sa.Column('provider_name', sa.String(length=64), nullable=True),
    sa.Column('source_confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('external_id', sa.String(length=128), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['buyer_id'], ['buyers.id'], name=op.f('fk_shipments_buyer_id_buyers'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_shipments')),
    sa.UniqueConstraint('external_id', name=op.f('uq_shipments_external_id'))
    )
    op.create_index(op.f('ix_shipments_buyer_id'), 'shipments', ['buyer_id'], unique=False)
    op.create_index('ix_shipments_hs_dest_date', 'shipments', ['hs_code', 'dest_iso2', 'shipment_date'], unique=False)
    op.create_table('emails',
    sa.Column('campaign_id', sa.UUID(), nullable=False),
    sa.Column('contact_id', sa.UUID(), nullable=False),
    sa.Column('buyer_id', sa.UUID(), nullable=False),
    sa.Column('status', postgresql.ENUM('draft', 'approved', 'rejected', 'queued', 'sent', 'opened', 'replied', 'bounced', 'complained', 'blocked_suppressed', 'cancelled', name='email_status', create_type=False), nullable=False),
    sa.Column('subject', sa.String(length=512), nullable=False),
    sa.Column('body_text', sa.Text(), nullable=False),
    sa.Column('body_html', sa.Text(), nullable=True),
    sa.Column('language', sa.String(length=2), nullable=False),
    sa.Column('is_followup', sa.Boolean(), nullable=False),
    sa.Column('followup_number', sa.Integer(), nullable=False),
    sa.Column('parent_email_id', sa.UUID(), nullable=True),
    sa.Column('unsubscribe_token', sa.String(length=64), nullable=False),
    sa.Column('approved_by', sa.UUID(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejected_by', sa.UUID(), nullable=True),
    sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejection_note', sa.Text(), nullable=True),
    sa.Column('edited_by_user', sa.Boolean(), nullable=False),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('bounced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('bounce_type', sa.String(length=32), nullable=True),
    sa.Column('blocked_reason', sa.String(length=255), nullable=True),
    sa.Column('provider_name', sa.String(length=64), nullable=True),
    sa.Column('provider_message_id', sa.String(length=128), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status NOT IN ('queued', 'sent', 'opened', 'replied', 'bounced', 'complained') OR (approved_at IS NOT NULL AND approved_by IS NOT NULL)", name=op.f('ck_emails_sent_requires_approval')),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_emails_approved_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['buyer_id'], ['buyers.id'], name=op.f('fk_emails_buyer_id_buyers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], name=op.f('fk_emails_campaign_id_campaigns'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_emails_contact_id_contacts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_email_id'], ['emails.id'], name=op.f('fk_emails_parent_email_id_emails'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['rejected_by'], ['users.id'], name=op.f('fk_emails_rejected_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_emails')),
    sa.UniqueConstraint('unsubscribe_token', name=op.f('uq_emails_unsubscribe_token'))
    )
    op.create_index('ix_emails_campaign_status', 'emails', ['campaign_id', 'status'], unique=False)
    op.create_index(op.f('ix_emails_contact_id'), 'emails', ['contact_id'], unique=False)
    op.create_index(op.f('ix_emails_provider_message_id'), 'emails', ['provider_message_id'], unique=False)
    op.create_table('lia_records',
    sa.Column('campaign_id', sa.UUID(), nullable=False),
    sa.Column('purpose_text', sa.Text(), nullable=False),
    sa.Column('necessity_text', sa.Text(), nullable=False),
    sa.Column('balancing_test_text', sa.Text(), nullable=False),
    sa.Column('data_sources', sa.Text(), nullable=True),
    sa.Column('completed_by', sa.UUID(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], name=op.f('fk_lia_records_campaign_id_campaigns'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['completed_by'], ['users.id'], name=op.f('fk_lia_records_completed_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lia_records')),
    sa.UniqueConstraint('campaign_id', name=op.f('uq_lia_records_campaign_id'))
    )
    op.create_table('suppression_list',
    sa.Column('email_norm', sa.String(length=255), nullable=False),
    sa.Column('reason', postgresql.ENUM('unsubscribe', 'bounce', 'complaint', 'manual', 'legal', name='suppression_reason', create_type=False), nullable=False),
    sa.Column('source_email_id', sa.UUID(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['source_email_id'], ['emails.id'], name=op.f('fk_suppression_list_source_email_id_emails'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suppression_list'))
    )
    op.create_index(op.f('ix_suppression_list_email_norm'), 'suppression_list', ['email_norm'], unique=True)

    # audit_log is append-only: the trigger rejects UPDATE and DELETE outright,
    # so the approval trail cannot be rewritten even by a direct SQL session.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
        """
    )


def downgrade() -> None:

    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
    op.drop_index(op.f('ix_suppression_list_email_norm'), table_name='suppression_list')
    op.drop_table('suppression_list')
    op.drop_table('lia_records')
    op.drop_index(op.f('ix_emails_provider_message_id'), table_name='emails')
    op.drop_index(op.f('ix_emails_contact_id'), table_name='emails')
    op.drop_index('ix_emails_campaign_status', table_name='emails')
    op.drop_table('emails')
    op.drop_index('ix_shipments_hs_dest_date', table_name='shipments')
    op.drop_index(op.f('ix_shipments_buyer_id'), table_name='shipments')
    op.drop_table('shipments')
    op.drop_index('ix_product_buyer_matches_product_score', table_name='product_buyer_matches', postgresql_ops={'relevance_score': 'DESC'})
    op.drop_index(op.f('ix_product_buyer_matches_market_iso2'), table_name='product_buyer_matches')
    op.drop_index(op.f('ix_product_buyer_matches_buyer_id'), table_name='product_buyer_matches')
    op.drop_table('product_buyer_matches')
    op.drop_index(op.f('ix_hs_corrections_product_id'), table_name='hs_corrections')
    op.drop_table('hs_corrections')
    op.drop_index(op.f('ix_contacts_email'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_buyer_id'), table_name='contacts')
    op.drop_table('contacts')
    op.drop_index(op.f('ix_campaigns_product_id'), table_name='campaigns')
    op.drop_index(op.f('ix_campaigns_market_iso2'), table_name='campaigns')
    op.drop_index(op.f('ix_campaigns_factory_id'), table_name='campaigns')
    op.drop_table('campaigns')
    op.drop_index(op.f('ix_audit_log_factory_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_entity_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_actor_user_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_action'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index(op.f('ix_users_factory_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_products_hs_code'), table_name='products')
    op.drop_index(op.f('ix_products_factory_id'), table_name='products')
    op.drop_table('products')
    op.drop_index(op.f('ix_buyers_domain'), table_name='buyers')
    op.drop_index('ix_buyers_country_iso2', table_name='buyers')
    op.drop_table('buyers')
    op.drop_table('markets')
    op.drop_index(op.f('ix_market_snapshots_market_iso2'), table_name='market_snapshots')
    op.drop_index(op.f('ix_market_snapshots_hs_code'), table_name='market_snapshots')
    op.drop_table('market_snapshots')
    op.drop_index(op.f('ix_hs_codes_sector'), table_name='hs_codes')
    op.drop_index(op.f('ix_hs_codes_parent_code'), table_name='hs_codes')
    op.drop_table('hs_codes')
    op.drop_index(op.f('ix_factories_sector'), table_name='factories')
    op.drop_table('factories')
    for enum_name in (
        "suppression_reason",
        "campaign_status",
        "buyer_source",
        "verification_status",
        "email_status",
        "user_role",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

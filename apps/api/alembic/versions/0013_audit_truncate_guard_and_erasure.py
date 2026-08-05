"""Audit-log TRUNCATE guard + unblock erasure of an approver (C6).

Two audit findings:

* The append-only ``audit_log`` trigger rejected UPDATE/DELETE but NOT TRUNCATE,
  so a direct SQL session (or a careless reset) could wipe the trail wholesale.
  Add a statement-level ``BEFORE TRUNCATE`` trigger (reusing the same
  ``audit_log_immutable()`` function) and revoke TRUNCATE from PUBLIC.
* ``emails.approved_by`` is ``ON DELETE SET NULL`` while the sent-requires-approval
  CHECK demanded ``approved_by IS NOT NULL`` — so erasing the user who approved a
  *sent* email violated the CHECK and was impossible (blocking PDPL erasure /
  offboarding). Snapshot the approver into ``approved_by_label`` and relax the
  CHECK to key on ``approved_at`` only; who approved is preserved in the label.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None

_SENT_FAMILY = "'queued', 'sent', 'opened', 'replied', 'bounced', 'complained'"
_CHECK = "ck_emails_sent_requires_approval"


def upgrade() -> None:
    # -- erasure conflict: snapshot the approver, relax the CHECK ------------
    op.add_column("emails", sa.Column("approved_by_label", sa.String(length=255), nullable=True))
    op.execute(f"ALTER TABLE emails DROP CONSTRAINT {_CHECK}")
    op.execute(
        f"ALTER TABLE emails ADD CONSTRAINT {_CHECK} "
        f"CHECK (status NOT IN ({_SENT_FAMILY}) OR approved_at IS NOT NULL)"
    )

    # -- audit_log: keep append-only, but let user/factory erasure null the FK --
    # The immutability trigger blocked EVERY update — including the ON DELETE SET
    # NULL that erasing a referenced user/factory must apply to actor_user_id /
    # factory_id. That made anyone who ever performed an audited action
    # undeletable (a PDPL/offboarding wall). Relax the function to permit ONLY
    # that null-ing: every content column (action, entity, actor_label, payload,
    # timestamps) must stay identical and an FK may only move to NULL, never to a
    # different value — so the trail stays tamper-evident and actor_label
    # preserves who acted, while a deleted subject's pointer can be cleared.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND NEW.id          IS NOT DISTINCT FROM OLD.id
               AND NEW.actor_label IS NOT DISTINCT FROM OLD.actor_label
               AND NEW.action      IS NOT DISTINCT FROM OLD.action
               AND NEW.entity_type IS NOT DISTINCT FROM OLD.entity_type
               AND NEW.entity_id   IS NOT DISTINCT FROM OLD.entity_id
               AND NEW.payload     IS NOT DISTINCT FROM OLD.payload
               AND NEW.occurred_at IS NOT DISTINCT FROM OLD.occurred_at
               AND NEW.created_at  IS NOT DISTINCT FROM OLD.created_at
               AND NEW.updated_at  IS NOT DISTINCT FROM OLD.updated_at
               AND (NEW.actor_user_id IS NULL
                    OR NEW.actor_user_id IS NOT DISTINCT FROM OLD.actor_user_id)
               AND (NEW.factory_id IS NULL
                    OR NEW.factory_id IS NOT DISTINCT FROM OLD.factory_id)
            THEN
                RETURN NEW;  -- privacy-mandated FK null-ing; content untouched
            END IF;
            RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # ...and also reject TRUNCATE (the function raises for any non-erasure op).
    op.execute(
        """
        CREATE TRIGGER audit_log_no_truncate
        BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable();
        """
    )
    # Defence in depth: no role should hold TRUNCATE on the ledger. The trigger is
    # the portable guarantee (it fires regardless of role/ownership); this revoke
    # documents intent and removes any PUBLIC grant.
    op.execute("REVOKE TRUNCATE ON TABLE audit_log FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    # Restore the strict function (raise on ANY update/delete/truncate).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(f"ALTER TABLE emails DROP CONSTRAINT {_CHECK}")
    op.execute(
        f"ALTER TABLE emails ADD CONSTRAINT {_CHECK} "
        f"CHECK (status NOT IN ({_SENT_FAMILY}) "
        "OR (approved_at IS NOT NULL AND approved_by IS NOT NULL))"
    )
    op.drop_column("emails", "approved_by_label")

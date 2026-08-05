"""C6 — erasing a user who approved sent mail succeeds, trail intact.

``emails.approved_by`` is ``ON DELETE SET NULL``; the old sent-requires-approval
CHECK demanded ``approved_by IS NOT NULL``, so deleting the approver of a *sent*
email violated the CHECK and was impossible (blocking PDPL erasure / offboarding).
The CHECK now keys on ``approved_at``, and ``approved_by_label`` preserves who
approved — so erasure succeeds without losing the record or the audit trail.
"""

from __future__ import annotations

from app.models import AuditLog, Email, EmailStatus, User, utcnow
from app.services import approval
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def test_erase_user_who_approved_sent_mail_succeeds(db, factory, product, admin_user):
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    approval.approve(db, email, admin_user)
    # Promote to a sent-family status; the CHECK now keys on approved_at.
    email.status = EmailStatus.sent
    email.sent_at = utcnow()
    db.commit()

    approver_id = admin_user.id
    approver_email = admin_user.email

    # The erasure that used to be impossible.
    db.delete(admin_user)
    db.commit()

    assert db.get(User, approver_id) is None

    db.expire_all()
    row = db.get(Email, email.id)
    assert row is not None
    assert row.status == EmailStatus.sent
    assert row.approved_by is None  # nulled by the FK on user erasure
    assert row.approved_at is not None  # the human act stays recorded
    assert row.approved_by_label == approver_email  # who approved is preserved

    # The audit trail survives: the row remains, actor nulled but its label kept.
    entry = db.query(AuditLog).filter(AuditLog.action == "approve_email").one()
    assert entry.actor_user_id is None
    assert entry.actor_label == approver_email

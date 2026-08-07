"""The email approval state machine — the platform's single most important rule.

No email is ever sent without an explicit human approval. That guarantee is
enforced in three independent places:

1. Here, at the service layer: ``transition`` is the *only* sanctioned way to
   change an email's status, and it rejects any move that isn't in
   ``ALLOWED_TRANSITIONS``. Approval writes the approver id + timestamp; queuing
   re-checks suppression, deliverability, and (for EU) the LIA record.
2. In the send worker (``services.sending``): the row is re-read under a lock and
   the approval, suppression, and deliverability checks run again before the
   provider is called.
3. In the database: a CHECK constraint makes a sent-family status without an
   approver physically unstorable.

Follow-ups are created as fresh drafts and traverse this same machine, so an
automated follow-up can never bypass approval.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Campaign, Email, EmailStatus, LIARecord, Market, User, utcnow
from app.services import audit, suppression

log = get_logger(__name__)


class TransitionError(HTTPException):
    def __init__(self, detail: str, code: int = status.HTTP_409_CONFLICT) -> None:
        super().__init__(status_code=code, detail=detail)


#: The complete set of legal status moves. Anything not listed is rejected.
ALLOWED_TRANSITIONS: dict[EmailStatus, set[EmailStatus]] = {
    EmailStatus.draft: {EmailStatus.approved, EmailStatus.rejected, EmailStatus.cancelled},
    EmailStatus.approved: {
        EmailStatus.queued,
        EmailStatus.rejected,
        EmailStatus.cancelled,
        EmailStatus.draft,  # editing an approved email sends it back to draft
    },
    EmailStatus.rejected: {EmailStatus.draft},
    EmailStatus.queued: {
        EmailStatus.sent,
        EmailStatus.blocked_suppressed,
        EmailStatus.bounced,
        EmailStatus.cancelled,
    },
    EmailStatus.sent: {
        EmailStatus.opened,
        EmailStatus.replied,
        EmailStatus.bounced,
        EmailStatus.complained,
    },
    EmailStatus.opened: {EmailStatus.replied, EmailStatus.complained},
    EmailStatus.replied: {EmailStatus.complained},
    EmailStatus.bounced: set(),
    EmailStatus.complained: set(),
    EmailStatus.blocked_suppressed: set(),
    EmailStatus.cancelled: set(),
}


def _assert_allowed(current: EmailStatus, target: EmailStatus) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise TransitionError(f"Cannot move email from {current.value} to {target.value}")


def approve(db: Session, email: Email, actor: User) -> Email:
    """Record explicit human approval. Required before an email can be queued."""
    _assert_allowed(email.status, EmailStatus.approved)
    email.status = EmailStatus.approved
    email.approved_by = actor.id
    # Durable snapshot so the approval trail survives erasure of the approver's
    # user row (approved_by is nulled by ON DELETE SET NULL; this label is not).
    email.approved_by_label = actor.email
    email.approved_at = utcnow()
    db.flush()
    audit.record(
        db,
        action="approve_email",
        entity_type="email",
        entity_id=email.id,
        actor=actor,
        factory_id=_factory_id(db, email),
        payload={"campaign_id": str(email.campaign_id), "contact_id": str(email.contact_id)},
    )
    log.info("email_approved", email_id=str(email.id), actor=str(actor.id))
    return email


def reject(db: Session, email: Email, actor: User, note: str | None = None) -> Email:
    _assert_allowed(email.status, EmailStatus.rejected)
    email.status = EmailStatus.rejected
    email.rejected_by = actor.id
    email.rejected_at = utcnow()
    email.rejection_note = note
    db.flush()
    audit.record(
        db,
        action="reject_email",
        entity_type="email",
        entity_id=email.id,
        actor=actor,
        factory_id=_factory_id(db, email),
        payload={"note": note},
    )
    return email


def revert_to_draft(db: Session, email: Email, actor: User) -> Email:
    """Send an approved/rejected email back to draft for editing.

    This deliberately clears the recorded approval so an edited message must be
    re-approved before it can go out.
    """
    _assert_allowed(email.status, EmailStatus.draft)
    email.status = EmailStatus.draft
    email.approved_by = None
    email.approved_by_label = None
    email.approved_at = None
    db.flush()
    return email


def queue(db: Session, email: Email, actor: User) -> Email:
    """Move an approved email into the send queue after the pre-send gate.

    The gate re-runs every hard check so nothing slips through between approval
    and queueing: approval present, recipient not suppressed, EU LIA on file,
    and the factory's deliverability state healthy.
    """
    from app.models import Contact
    from app.services import deliverability

    _assert_allowed(email.status, EmailStatus.queued)

    if not email.is_approved:
        raise TransitionError("Email must be approved before queueing")

    contact = db.get(Contact, email.contact_id)
    if contact and suppression.is_suppressed(db, contact.email):
        email.status = EmailStatus.blocked_suppressed
        email.blocked_reason = "recipient on suppression list"
        db.flush()
        audit.record(
            db,
            action="block_suppressed",
            entity_type="email",
            entity_id=email.id,
            actor=actor,
            payload={"email": contact.email},
        )
        raise TransitionError("Recipient is on the suppression list", code=status.HTTP_409_CONFLICT)

    campaign = db.get(Campaign, email.campaign_id)
    _assert_lia_if_eu(db, campaign)

    # Governance must match what the send worker will actually enforce
    # (audit 2026-08-07 C4): an account-bound campaign is governed by the
    # MAILBOX's counters/warm-up, not the factory-domain legacy path — the old
    # factory-only check here waved sends through that the worker then blocked,
    # stranding them in `queued`.
    if campaign is not None and campaign.sender_account_id:
        from app.models import SenderAccount
        from app.services import sender_accounts

        account = db.get(SenderAccount, campaign.sender_account_id)
        gov = sender_accounts.can_send_from(db, account) if account is not None else None
        if account is None or gov is None or not gov.ok:
            reason = (gov.reason if gov else None) or "sender mailbox unavailable"
            raise TransitionError(reason)
    else:
        check = deliverability.can_send(db, campaign)
        if not check.ok:
            raise TransitionError(check.reason or "Sending is currently blocked")

    email.status = EmailStatus.queued
    email.queued_at = utcnow()
    db.flush()
    audit.record(
        db,
        action="queue_email",
        entity_type="email",
        entity_id=email.id,
        actor=actor,
        factory_id=_factory_id(db, email),
    )
    log.info("email_queued", email_id=str(email.id))
    return email


def _assert_lia_if_eu(db: Session, campaign: Campaign) -> None:
    market = db.get(Market, campaign.market_iso2)
    if market is None or not market.is_eu:
        return
    lia = db.scalar(LIARecord.__table__.select().where(LIARecord.campaign_id == campaign.id))
    if lia is None:
        raise TransitionError(
            "A Legitimate Interest Assessment is required before emailing an EU market",
            code=status.HTTP_412_PRECONDITION_FAILED,
        )


def _factory_id(db: Session, email: Email):
    campaign = db.get(Campaign, email.campaign_id)
    return campaign.factory_id if campaign else None

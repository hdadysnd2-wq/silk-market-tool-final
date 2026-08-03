"""Reply detection and sequence stopping.

A Celery beat task polls each connected mailbox (read scope) for new messages;
this module turns a detected reply into the right state changes: the replied-to
email is marked ``replied``, that contact's remaining sequence is stopped (any
pending follow-ups cancelled so we never email someone who already answered), and
the factory is notified. Every reply and stop is written to the immutable audit
log.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Campaign, Contact, Email, EmailStatus, SenderAccount, utcnow
from app.providers.base import MailboxCredentials, MailboxProvider, ReplyMessage
from app.services import audit, notifications

log = get_logger(__name__)

#: Statuses of outbound emails that a reply should cancel (the "sequence").
_PENDING = (EmailStatus.draft, EmailStatus.approved, EmailStatus.queued)


def handle_reply(db: Session, account: SenderAccount, reply: ReplyMessage) -> bool:
    """Apply one detected reply. Returns True if it matched an outbound email.

    Idempotent: a reply whose thread is already marked ``replied`` is ignored.
    """
    from_norm = reply.from_email.strip().lower()

    # Find the most recent email this account sent to the replying address.
    candidate = db.scalar(
        select(Email)
        .join(Contact, Contact.id == Email.contact_id)
        .join(Campaign, Campaign.id == Email.campaign_id)
        .where(
            Campaign.sender_account_id == account.id,
            func.lower(func.trim(Contact.email)) == from_norm,
            Email.status.in_((EmailStatus.sent, EmailStatus.opened, EmailStatus.replied)),
        )
        .order_by(Email.sent_at.desc().nullslast())
    )
    if candidate is None:
        return False
    if candidate.status == EmailStatus.replied:
        return False  # already handled

    campaign = db.get(Campaign, candidate.campaign_id)
    if candidate.status == EmailStatus.sent:
        candidate.opened_at = candidate.opened_at or utcnow()
        if campaign:
            campaign.opened_count += 1
    candidate.status = EmailStatus.replied
    candidate.replied_at = utcnow()
    if campaign:
        campaign.replied_count += 1
    db.flush()

    stopped = _stop_sequence(db, account, candidate.contact_id, cause_email_id=candidate.id)

    audit.record(
        db,
        action="reply_received",
        entity_type="email",
        entity_id=candidate.id,
        actor_label="system",
        factory_id=account.factory_id,
        payload={"from": from_norm, "sequence_cancelled": stopped},
    )
    notifications.notify(
        db,
        factory_id=account.factory_id,
        kind="reply_received",
        title="New reply received",
        body=f"{reply.from_email} replied. Their remaining sequence was stopped.",
        entity_type="email",
        entity_id=candidate.id,
    )
    log.info("reply_handled", account_id=str(account.id), stopped=stopped)
    return True


def _stop_sequence(db: Session, account: SenderAccount, contact_id, *, cause_email_id) -> int:
    """Cancel this contact's pending emails across the account's campaigns."""
    pending = db.scalars(
        select(Email)
        .join(Campaign, Campaign.id == Email.campaign_id)
        .where(
            Campaign.sender_account_id == account.id,
            Email.contact_id == contact_id,
            Email.status.in_(_PENDING),
        )
    ).all()
    count = 0
    for email in pending:
        email.status = EmailStatus.cancelled
        email.blocked_reason = "contact replied — sequence stopped"
        count += 1
    if count:
        db.flush()
        audit.record(
            db,
            action="sequence_stopped",
            entity_type="email",
            entity_id=cause_email_id,
            actor_label="system",
            factory_id=account.factory_id,
            payload={"cancelled": count},
        )
    return count


def poll_account(
    db: Session,
    account: SenderAccount,
    provider: MailboxProvider,
    creds: MailboxCredentials,
    since: datetime,
) -> int:
    """Fetch replies for one mailbox and handle each. Returns replies matched."""
    matched = 0
    for reply in provider.fetch_replies(creds, since):
        if handle_reply(db, account, reply):
            matched += 1
    account.last_polled_at = utcnow()
    db.flush()
    return matched

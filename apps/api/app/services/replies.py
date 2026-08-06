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
from app.models import (
    Campaign,
    Contact,
    Email,
    EmailStatus,
    SenderAccount,
    SuppressionReason,
    utcnow,
)
from app.providers.base import MailboxCredentials, MailboxProvider, ReplyMessage
from app.services import audit, deliverability, notifications, suppression

log = get_logger(__name__)

#: Statuses of outbound emails that a reply should cancel (the "sequence").
_PENDING = (EmailStatus.draft, EmailStatus.approved, EmailStatus.queued)

#: Local-part prefixes an NDR/bounce is sent *from* (Gmail: mailer-daemon;
#: Exchange: postmaster / MicrosoftExchange…). A message from one of these that
#: also names a failed recipient is a delivery failure, not a human reply.
_NDR_SENDER_PREFIXES = (
    "mailer-daemon",
    "mail-daemon",
    "maildaemon",
    "postmaster",
    "microsoftexchange",
)


def is_bounce(reply: ReplyMessage) -> bool:
    """True if this mailbox message is a delivery-failure notification (NDR).

    Requires both a machine sender (mailer-daemon/postmaster/Exchange) and a
    parsed failed recipient — without the latter we cannot attribute the bounce,
    so we treat it as an ordinary (unmatched) message rather than guessing.
    ``failed_recipient`` is only ever populated by the provider adapters on a
    genuine NDR, so a human reply can never be misclassified here.
    """
    if not reply.failed_recipient:
        return False
    local = reply.from_email.split("@", 1)[0].strip().lower()
    return any(local.startswith(p) for p in _NDR_SENDER_PREFIXES)


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


def handle_bounce(db: Session, account: SenderAccount, reply: ReplyMessage) -> bool:
    """Apply one delivery-failure notification. Returns True if it matched a send.

    This is the connected-mailbox (Gmail/Microsoft) counterpart to the webhook
    bounce path in ``services.sending.record_engagement``: mailbox sends receive
    no provider webhook, so bounces arrive only as NDRs in the inbox. Matching is
    by the *failed* recipient address (NDRs come from mailer-daemon, never the
    prospect). On a match the email is marked ``bounced``, the address is
    suppressed, the campaign's bounce counter advances, and campaign health is
    re-evaluated so the 5% auto-pause guardrail can fire on the real send path.

    Idempotent: an already-``bounced`` email is ignored.
    """
    failed_norm = (reply.failed_recipient or "").strip().lower()
    if not failed_norm:
        return False

    candidate = db.scalar(
        select(Email)
        .join(Contact, Contact.id == Email.contact_id)
        .join(Campaign, Campaign.id == Email.campaign_id)
        .where(
            Campaign.sender_account_id == account.id,
            func.lower(func.trim(Contact.email)) == failed_norm,
            Email.status.in_((EmailStatus.sent, EmailStatus.opened, EmailStatus.bounced)),
        )
        .order_by(Email.sent_at.desc().nullslast())
    )
    if candidate is None:
        log.warning(
            "mailbox_ndr_unmatched",
            account_id=str(account.id),
            failed_recipient=failed_norm,
        )
        return False
    if candidate.status == EmailStatus.bounced:
        return False  # already handled

    campaign = db.get(Campaign, candidate.campaign_id)
    candidate.status = EmailStatus.bounced
    candidate.bounced_at = utcnow()
    candidate.bounce_type = "hard"
    if campaign:
        campaign.bounced_count += 1
    db.flush()

    contact = db.get(Contact, candidate.contact_id)
    if contact:
        suppression.suppress(
            db,
            email=contact.email,
            reason=SuppressionReason.bounce,
            source_email_id=candidate.id,
            actor_label="system",
        )

    audit.record(
        db,
        action="bounce_received",
        entity_type="email",
        entity_id=candidate.id,
        actor_label="system",
        factory_id=account.factory_id,
        payload={"failed_recipient": failed_norm, "channel": "mailbox_ndr"},
    )
    if campaign:
        deliverability.evaluate_campaign_health(db, campaign)
    log.info("mailbox_bounce_handled", account_id=str(account.id))
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
    """Fetch messages for one mailbox and handle each. Returns replies matched.

    A fetched message is routed as a bounce (NDR) or a human reply — never both.
    Bounces are actioned but do not count toward the returned reply tally.
    """
    matched = 0
    for message in provider.fetch_replies(creds, since):
        if is_bounce(message):
            handle_bounce(db, account, message)
        elif handle_reply(db, account, message):
            matched += 1
    account.last_polled_at = utcnow()
    db.flush()
    return matched

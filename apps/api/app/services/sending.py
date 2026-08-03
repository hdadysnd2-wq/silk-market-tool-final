"""The guarded send path — enforcement layer 2.

Even though the API already approved and queued the email, this function re-reads
the row under a row lock and independently re-verifies every hard invariant
before touching the sending provider:

* the email is still ``queued`` and carries a recorded approval,
* the recipient is not on the suppression list (it may have been added *after*
  queueing — the classic race the spec calls out),
* the factory's deliverability state still permits a send.

Any failed check aborts the send; the provider is only ever called once all of
them pass.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import (
    Campaign,
    CampaignStatus,
    Contact,
    Email,
    EmailStatus,
    Factory,
    SenderAccount,
    SuppressionReason,
    utcnow,
)
from app.providers.base import OutboundEmail, SendingProvider
from app.services import audit, deliverability, sender_accounts, suppression

log = get_logger(__name__)


class SendBlocked(Exception):
    """Raised when a queued email fails a pre-send re-check."""


class AccountBoundSender:
    """Adapts a per-account ``MailboxProvider`` to the ``(message) -> SendResult``
    sender interface ``send_email`` expects.

    The worker resolves the campaign's connected mailbox, ensures valid (refreshed)
    credentials, and wraps them here so ``send_email`` stays agnostic to whether
    it is sending through a shared cold-email vendor or a tenant's own mailbox.
    """

    def __init__(self, provider, creds) -> None:
        self._provider = provider
        self._creds = creds
        self.name = getattr(provider, "name", "mailbox")

    def send(self, message: OutboundEmail):
        return self._provider.send(self._creds, message)


def send_email(db: Session, email_id: uuid.UUID, provider: SendingProvider) -> Email:
    """Send one queued email, or block it. Never sends an unapproved message."""
    # Lock the row so a concurrent worker can't double-send it.
    email = db.execute(
        select(Email).where(Email.id == email_id).with_for_update()
    ).scalar_one_or_none()
    if email is None:
        raise SendBlocked("email not found")

    # --- Re-check 1: status + approval (defends against buggy callers) -------
    if email.status != EmailStatus.queued:
        raise SendBlocked(f"email is {email.status.value}, not queued")
    if not email.is_approved:
        # Should be impossible given the CHECK constraint, but we never send an
        # email we cannot prove was approved.
        raise SendBlocked("email is not approved")

    contact = db.get(Contact, email.contact_id)
    campaign = db.get(Campaign, email.campaign_id)
    factory = db.get(Factory, campaign.factory_id)

    # The connected mailbox this campaign sends from, if any. When present, the
    # per-account governance below is authoritative; legacy campaigns with no
    # connected mailbox keep the factory-domain deliverability path.
    account = (
        db.get(SenderAccount, campaign.sender_account_id)
        if campaign and campaign.sender_account_id
        else None
    )

    # --- Re-check 2: send governance -----------------------------------------
    if account is not None:
        # Per-account governance: honour global pauses, then the mailbox's own
        # daily counter + warm-up limit + reauth state (all enforced here, in the
        # worker — never in the UI).
        if factory and factory.sends_paused:
            raise SendBlocked(f"Factory sending paused: {factory.paused_reason or 'manual'}")
        if campaign.status in (CampaignStatus.paused, CampaignStatus.auto_paused):
            raise SendBlocked(f"Campaign {campaign.status.value}: {campaign.paused_reason or ''}")
        gov = sender_accounts.can_send_from(db, account)
        if not gov.ok:
            raise SendBlocked(gov.reason or "sender account cannot send")
    else:
        check = deliverability.can_send(db, campaign)
        if not check.ok:
            raise SendBlocked(check.reason or "deliverability check failed")

    # --- Re-check 3: suppression — the LAST gate before egress ---------------
    # Deliberately checked at send time (it may have arrived after queueing) and
    # last, so it is the final word before the message leaves the building.
    if contact and suppression.is_suppressed(db, contact.email):
        email.status = EmailStatus.blocked_suppressed
        email.blocked_reason = "recipient suppressed before send"
        db.flush()
        audit.record(
            db,
            action="send_blocked_suppressed",
            entity_type="email",
            entity_id=email.id,
            actor_label="system",
            factory_id=factory.id if factory else None,
            payload={"email": contact.email},
        )
        log.info("send_blocked_suppressed", email_id=str(email.id))
        return email

    # --- All checks passed: hand to the provider -----------------------------
    message = _build_message(email, contact, factory, campaign, account)
    result = provider.send(message)
    if not result.accepted:
        raise SendBlocked(result.error or "provider rejected the message")

    email.status = EmailStatus.sent
    email.sent_at = utcnow()
    email.provider_name = result.provider_name
    email.provider_message_id = result.provider_message_id

    campaign.sent_count += 1
    if account is not None:
        sender_accounts.register_account_send(db, account)
    else:
        deliverability.register_send(db, factory)

    db.flush()
    audit.record(
        db,
        action="send_email",
        entity_type="email",
        entity_id=email.id,
        actor_label="system",
        factory_id=factory.id,
        payload={
            "provider_message_id": result.provider_message_id,
            "to": contact.email,
            "mailbox": account.email if account else None,
        },
    )
    log.info("email_sent", email_id=str(email.id), provider_message_id=result.provider_message_id)
    return email


def _build_message(
    email: Email,
    contact: Contact,
    factory: Factory,
    campaign: Campaign,
    account: SenderAccount | None = None,
) -> OutboundEmail:
    from app.services.email_drafting import unsubscribe_url

    # When a mailbox is connected we send AS that address (Gmail/Graph will only
    # send from the authenticated account); otherwise fall back to the factory's
    # configured sender identity.
    if account is not None:
        from_email = account.email
    else:
        from_local = "outreach"
        domain = factory.sending_domain or "example.com"
        from_email = factory.contact_email or f"{from_local}@{domain}"
    return OutboundEmail(
        to_email=contact.email,
        to_name=contact.full_name,
        subject=email.subject,
        body_text=email.body_text,
        body_html=email.body_html,
        from_name=factory.contact_person or factory.name_en,
        from_email=from_email,
        reply_to=factory.contact_email,
        sending_domain=factory.sending_domain,
        unsubscribe_url=unsubscribe_url(email.unsubscribe_token),
        campaign_ref=str(campaign.id),
        message_ref=str(email.id),
    )


def record_engagement(
    db: Session, provider_message_id: str, event: str, bounce_type: str | None = None
) -> Email | None:
    """Apply an inbound webhook engagement event to the matching email."""
    email = db.scalar(select(Email).where(Email.provider_message_id == provider_message_id))
    if email is None:
        return None

    campaign = db.get(Campaign, email.campaign_id)

    if event == "opened" and email.status in (EmailStatus.sent,):
        email.status = EmailStatus.opened
        email.opened_at = utcnow()
        campaign.opened_count += 1
    elif event == "replied" and email.status in (EmailStatus.sent, EmailStatus.opened):
        if email.status == EmailStatus.sent:
            campaign.opened_count += 1
            email.opened_at = email.opened_at or utcnow()
        email.status = EmailStatus.replied
        email.replied_at = utcnow()
        campaign.replied_count += 1
    elif event == "bounced":
        email.status = EmailStatus.bounced
        email.bounced_at = utcnow()
        email.bounce_type = bounce_type
        campaign.bounced_count += 1
        contact = db.get(Contact, email.contact_id)
        if contact:
            suppression.suppress(
                db,
                email=contact.email,
                reason=SuppressionReason.bounce,
                source_email_id=email.id,
                actor_label="system",
            )
    elif event == "complained":
        email.status = EmailStatus.complained
        campaign.complained_count += 1
        contact = db.get(Contact, email.contact_id)
        if contact:
            suppression.suppress(
                db,
                email=contact.email,
                reason=SuppressionReason.complaint,
                source_email_id=email.id,
                actor_label="system",
            )

    db.flush()
    deliverability.evaluate_campaign_health(db, campaign)
    return email

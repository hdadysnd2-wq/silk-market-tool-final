"""PDPL data-lifecycle jobs — retention (data minimisation) and erasure.

Personal data lives in ``Contact`` rows (email, full name, title). We
**anonymise** rather than delete: ``emails.contact_id`` carries ``ON DELETE
CASCADE``, so deleting a contact would also destroy the record of what was
actually sent — which CAN-SPAM / PDPL require us to keep. Anonymised data is no
longer personal data, so overwriting the PII columns meets the same obligation
without losing the business record.

Two guarantees hold throughout:

- The append-only ``audit_log`` is never mutated; every anonymisation *appends*
  an entry, and no original PII is written into that entry.
- Erasure keeps the address on the global suppression ledger — you cannot email
  someone you have "forgotten", and a later re-import must not reach them again.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging import get_logger
from app.models import Contact, Email, EmailStatus, SuppressionReason, User, utcnow
from app.services import audit, suppression

log = get_logger(__name__)

#: Anonymised addresses are parked on this reserved, non-routable domain.
_ANON_DOMAIN = "pdpl.invalid"

#: A contact with an email in one of these states is still being actively worked
#: on, so it is never anonymised by the retention sweep.
_LIVE_EMAIL_STATUSES = (
    EmailStatus.draft,
    EmailStatus.approved,
    EmailStatus.queued,
)


def is_anonymised(contact: Contact) -> bool:
    return contact.email.endswith(f"@{_ANON_DOMAIN}")


def _redacted_email(contact: Contact) -> str:
    # Unique per row so the (buyer_id, email) uniqueness and NOT NULL both hold.
    return f"redacted+{contact.id}@{_ANON_DOMAIN}"


def _has_live_email(db: Session, contact_id) -> bool:
    return (
        db.scalar(
            select(Email.id)
            .where(Email.contact_id == contact_id, Email.status.in_(_LIVE_EMAIL_STATUSES))
            .limit(1)
        )
        is not None
    )


def anonymise_contact(
    db: Session, contact: Contact, *, action: str, actor: User | None = None
) -> bool:
    """Strip a contact's personal data in place and audit it. Idempotent — a
    contact that is already anonymised is left untouched and returns ``False``."""
    if is_anonymised(contact):
        return False
    contact.email = _redacted_email(contact)
    contact.full_name = None
    contact.title = None
    db.flush()
    # Deliberately record no original PII in the ledger — only that it happened.
    audit.record(
        db,
        action=action,
        entity_type="contact",
        entity_id=contact.id,
        actor=actor,
        payload={"anonymised": True},
    )
    log.info("contact_anonymised", contact_id=str(contact.id), action=action)
    return True


def purge_stale_pii(
    db: Session, *, retention_days: int | None = None, now: datetime | None = None
) -> int:
    """Retention sweep: anonymise personal data on contacts older than the
    retention window that are not part of any live campaign email. Returns the
    number of contacts anonymised. Does not commit — the caller owns the txn."""
    days = retention_days if retention_days is not None else get_settings().pdpl_retention_days
    now = now or utcnow()
    cutoff = now - timedelta(days=days)

    stale = db.scalars(
        select(Contact).where(
            Contact.created_at < cutoff,
            Contact.email.not_like(f"%@{_ANON_DOMAIN}"),
        )
    ).all()

    count = 0
    for contact in stale:
        if _has_live_email(db, contact.id):
            continue
        if anonymise_contact(db, contact, action="pdpl_retention_anonymise"):
            count += 1

    log.info("pdpl_retention_run", anonymised=count, cutoff=cutoff.isoformat())
    return count


def erase_data_subject(db: Session, *, email: str, actor: User | None = None) -> int:
    """Erasure (right to be forgotten): anonymise every contact holding this
    address and suppress it globally so it can never be re-contacted. Returns the
    number of contacts anonymised. Works even when no contact row exists, so a
    request always results in a durable suppression. The audit log is preserved."""
    norm = suppression.normalize_email(email)

    contacts = db.scalars(select(Contact).where(func.lower(Contact.email) == norm)).all()
    erased = 0
    for contact in contacts:
        if anonymise_contact(db, contact, action="pdpl_erasure", actor=actor):
            erased += 1

    # A forgotten subject must stay unreachable even if re-imported later.
    suppression.suppress(
        db,
        email=norm,
        reason=SuppressionReason.legal,
        note="PDPL erasure request",
        actor=actor,
    )
    audit.record(
        db,
        action="pdpl_erasure_request",
        entity_type="data_subject",
        entity_id=norm,
        actor=actor,
        payload={"contacts_erased": erased},
    )
    log.info("pdpl_erasure", email=norm, contacts=erased)
    return erased

"""Central suppression ledger.

Every outbound send checks this table first; a hit is a hard block. Suppression
is global — one unsubscribe silences an address across every campaign and every
factory on the platform — which is the strictest reading of PDPL / GDPR /
CAN-SPAM and the safest default.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Email, EmailStatus, SuppressionEntry, SuppressionReason
from app.services import audit

log = get_logger(__name__)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_suppressed(db: Session, email: str) -> bool:
    return (
        db.scalar(
            select(SuppressionEntry.id).where(SuppressionEntry.email_norm == normalize_email(email))
        )
        is not None
    )


def suppress(
    db: Session,
    *,
    email: str,
    reason: SuppressionReason,
    source_email_id: uuid.UUID | None = None,
    note: str | None = None,
    actor=None,
    actor_label: str | None = None,
) -> SuppressionEntry:
    """Add an address to the ledger (idempotent) and audit it.

    Any pending (draft/approved/queued) email to the same address is cancelled so
    it can never be sent after the opt-out.
    """
    norm = normalize_email(email)
    entry = db.scalar(select(SuppressionEntry).where(SuppressionEntry.email_norm == norm))
    if entry is None:
        entry = SuppressionEntry(
            email_norm=norm,
            reason=reason,
            source_email_id=source_email_id,
            note=note,
        )
        db.add(entry)
        db.flush()
        audit.record(
            db,
            action="suppress_email",
            entity_type="suppression",
            entity_id=entry.id,
            actor=actor,
            actor_label=actor_label,
            payload={"email": norm, "reason": reason.value},
        )
        log.info("email_suppressed", email=norm, reason=reason.value)

    _cancel_pending_to(db, norm)
    return entry


def _cancel_pending_to(db: Session, email_norm: str) -> int:
    """Cancel *draft* emails to a now-suppressed contact.

    Drafts are cancelled outright. Emails already approved or queued represent an
    explicit human decision and a committed pipeline step, so they are left for
    the approval gate (``queue``) and the send worker to catch — those paths
    move them to the auditable ``blocked_suppressed`` state instead of silently
    cancelling an approved message.
    """
    from app.models import Contact

    # Contact.email is stored with inconsistent casing/whitespace across sources,
    # so normalize the stored column the same way ``normalize_email`` normalizes
    # the incoming address before comparing — otherwise a draft to
    # "John@X.com " would slip past the opt-out cancellation.
    rows = (
        db.execute(
            select(Email)
            .join(Contact, Contact.id == Email.contact_id)
            .where(
                func.lower(func.trim(Contact.email)) == email_norm,
                Email.status == EmailStatus.draft,
            )
        )
        .scalars()
        .all()
    )

    for email in rows:
        email.status = EmailStatus.cancelled
        email.blocked_reason = "recipient suppressed"
    if rows:
        db.flush()
    return len(rows)

"""Connected sender accounts: lookup + per-account send governance.

Governance (daily counter + warm-up ramp) is enforced here and called from the
send worker before every send — never from the UI. A new mailbox starts warm
(10–20/day) and ramps on a schedule so a freshly connected account does not blast
its full daily limit on day one and torch its sender reputation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import SenderAccount, SenderVerificationStatus, utcnow

log = get_logger(__name__)

#: Warm-up ramp: stage → emails/day. New accounts begin at stage 1 (15/day, in
#: the task's 10–20 band) and advance one stage per day via the daily beat until
#: they reach the account's own ``daily_send_limit`` ceiling.
WARMUP_STAGE_LIMITS: dict[int, int] = {
    1: 15,
    2: 25,
    3: 40,
    4: 60,
    5: 90,
    6: 130,
    7: 180,
    8: 250,
}
MAX_WARMUP_STAGE = max(WARMUP_STAGE_LIMITS)


@dataclass(frozen=True)
class AccountSendCheck:
    ok: bool
    reason: str | None = None
    daily_remaining: int = 0


def warmup_limit(account: SenderAccount) -> int:
    """Emails this account may send today, honouring both warm-up and the cap."""
    stage = max(1, account.warmup_stage)
    stage_cap = WARMUP_STAGE_LIMITS.get(stage, account.daily_send_limit)
    return min(stage_cap, account.daily_send_limit)


def _roll_daily_counter(db: Session, account: SenderAccount) -> None:
    """Zero the per-day counter when the calendar day (UTC) has rolled over."""
    today = datetime.now(UTC).date()
    if account.daily_counter_date is None or account.daily_counter_date.date() != today:
        account.daily_sent_count = 0
        account.daily_counter_date = utcnow()


def can_send_from(db: Session, account: SenderAccount) -> AccountSendCheck:
    """Whether this specific mailbox may send one more email right now."""
    if account.verification_status == SenderVerificationStatus.needs_reauth:
        return AccountSendCheck(False, "Sender mailbox needs reconnection")
    if account.verification_status != SenderVerificationStatus.verified:
        return AccountSendCheck(False, "Sender mailbox is not verified")

    _roll_daily_counter(db, account)
    cap = warmup_limit(account)
    remaining = cap - account.daily_sent_count
    if remaining <= 0:
        return AccountSendCheck(
            False, f"Daily send limit reached for this mailbox ({cap})", daily_remaining=0
        )
    return AccountSendCheck(True, daily_remaining=remaining)


def register_account_send(db: Session, account: SenderAccount) -> None:
    """Increment the mailbox's daily counter after a successful send."""
    _roll_daily_counter(db, account)
    account.daily_sent_count += 1
    db.flush()


def advance_warmup(db: Session, account: SenderAccount) -> bool:
    """Advance one warm-up stage (up to the max). Returns True if it moved."""
    if account.warmup_stage < MAX_WARMUP_STAGE:
        account.warmup_stage += 1
        db.flush()
        return True
    return False


# -- lookup / tenant-scoped queries ---------------------------------------


def list_for_factory(db: Session, factory_id: uuid.UUID) -> list[SenderAccount]:
    return list(
        db.scalars(
            select(SenderAccount)
            .where(SenderAccount.factory_id == factory_id)
            .order_by(SenderAccount.created_at.desc())
        ).all()
    )


def get_scoped(db: Session, account_id: uuid.UUID, factory_id: uuid.UUID) -> SenderAccount | None:
    """Fetch an account only if it belongs to ``factory_id`` (tenant isolation)."""
    return db.scalar(
        select(SenderAccount).where(
            SenderAccount.id == account_id,
            SenderAccount.factory_id == factory_id,
        )
    )


def default_verified_account(db: Session, factory_id: uuid.UUID) -> SenderAccount | None:
    """The factory's active mailbox to send from — most recently verified one."""
    return db.scalar(
        select(SenderAccount)
        .where(
            SenderAccount.factory_id == factory_id,
            SenderAccount.verification_status == SenderVerificationStatus.verified,
        )
        .order_by(SenderAccount.verified_at.desc().nullslast())
    )


def has_verified_account(db: Session, factory_id: uuid.UUID) -> bool:
    return default_verified_account(db, factory_id) is not None

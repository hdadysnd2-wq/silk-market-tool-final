"""Deliverability guardrails.

Encodes the spec's non-negotiable sending rules: DNS authentication must be in
place, domains warm up gradually, no inbox exceeds its daily cap, and a campaign
auto-pauses the moment its bounce or complaint rate crosses the threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging import get_logger
from app.models import Campaign, CampaignStatus, Factory, utcnow
from app.services import audit

log = get_logger(__name__)


@dataclass(frozen=True)
class SendCheck:
    ok: bool
    reason: str | None = None
    daily_remaining: int = 0


def warmup_cap(factory: Factory) -> int:
    """Emails a warming domain may send today: ramps 5/day up to the full cap."""
    settings = get_settings()
    full_cap = settings.max_emails_per_inbox_per_day * max(1, factory.inbox_count)
    if factory.warmup_started_at is None:
        # Not warming yet — treat as day 0, minimal volume.
        return min(5, full_cap)
    day = max(1, factory.warmup_day)
    return min(5 * day, full_cap)


def can_send(db: Session, campaign: Campaign) -> SendCheck:
    """Whether one more email may be sent for this campaign right now."""
    factory = db.get(Factory, campaign.factory_id)
    if factory is None:
        return SendCheck(False, "Factory not found")

    if factory.sends_paused:
        return SendCheck(False, f"Factory sending paused: {factory.paused_reason or 'manual'}")

    if campaign.status in (CampaignStatus.paused, CampaignStatus.auto_paused):
        return SendCheck(False, f"Campaign {campaign.status.value}: {campaign.paused_reason or ''}")

    if not (factory.spf_ok and factory.dkim_ok and factory.dmarc_ok):
        return SendCheck(False, "SPF, DKIM and DMARC must all be verified before sending")

    if not factory.sending_domain:
        return SendCheck(False, "No dedicated sending domain configured")

    _roll_daily_counter(db, factory)
    cap = warmup_cap(factory)
    remaining = cap - factory.daily_send_count
    if remaining <= 0:
        return SendCheck(False, f"Daily send cap reached ({cap})", daily_remaining=0)

    return SendCheck(True, daily_remaining=remaining)


def register_send(db: Session, factory: Factory) -> None:
    """Increment the factory's daily counter after a successful send."""
    _roll_daily_counter(db, factory)
    factory.daily_send_count += 1
    db.flush()


def _roll_daily_counter(db: Session, factory: Factory) -> None:
    today = datetime.now(UTC).date()
    if factory.daily_counter_date is None or factory.daily_counter_date.date() != today:
        factory.daily_send_count = 0
        factory.daily_counter_date = utcnow()


def evaluate_campaign_health(db: Session, campaign: Campaign) -> bool:
    """Auto-pause a campaign whose bounce/complaint rate is too high.

    Returns True if the campaign was paused by this call. Needs a minimum volume
    so a single early bounce doesn't trip the rule.
    """
    settings = get_settings()
    if campaign.sent_count < 20:
        return False
    if campaign.status in (CampaignStatus.paused, CampaignStatus.auto_paused):
        return False

    reason = None
    if campaign.bounce_rate > settings.bounce_rate_pause_threshold:
        reason = (
            f"bounce rate {campaign.bounce_rate:.1%} exceeds "
            f"{settings.bounce_rate_pause_threshold:.0%}"
        )
    elif campaign.complaint_rate > settings.complaint_rate_pause_threshold:
        reason = (
            f"complaint rate {campaign.complaint_rate:.2%} exceeds "
            f"{settings.complaint_rate_pause_threshold:.1%}"
        )

    if reason is None:
        return False

    campaign.status = CampaignStatus.auto_paused
    campaign.paused_reason = reason
    db.flush()
    audit.record(
        db,
        action="auto_pause_campaign",
        entity_type="campaign",
        entity_id=campaign.id,
        actor_label="system",
        factory_id=campaign.factory_id,
        payload={"reason": reason},
    )
    log.warning("campaign_auto_paused", campaign_id=str(campaign.id), reason=reason)
    return True

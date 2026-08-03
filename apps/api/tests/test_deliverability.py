"""Deliverability guardrails: DNS gating, warm-up caps, and auto-pause."""

from __future__ import annotations

from app.models import CampaignStatus, utcnow
from app.services import deliverability
from tests.conftest import make_campaign


def test_send_blocked_without_dns(db, factory, product):
    factory.spf_ok = False
    campaign = make_campaign(db, factory, product)
    check = deliverability.can_send(db, campaign)
    assert not check.ok
    assert "DKIM" in check.reason or "SPF" in check.reason


def test_send_blocked_without_domain(db, factory, product):
    factory.sending_domain = None
    campaign = make_campaign(db, factory, product)
    assert not deliverability.can_send(db, campaign).ok


def test_warmup_cap_ramps(db, factory):
    factory.warmup_started_at = utcnow()
    factory.inbox_count = 1
    factory.warmup_day = 1
    assert deliverability.warmup_cap(factory) == 5
    factory.warmup_day = 4
    assert deliverability.warmup_cap(factory) == 20
    factory.warmup_day = 14
    assert deliverability.warmup_cap(factory) == 50  # capped at the daily max


def test_daily_cap_blocks_when_reached(db, factory, product):
    campaign = make_campaign(db, factory, product)
    factory.daily_send_count = 50
    factory.daily_counter_date = utcnow()
    check = deliverability.can_send(db, campaign)
    assert not check.ok
    assert "cap" in check.reason.lower()


def test_auto_pause_on_high_bounce_rate(db, factory, product):
    campaign = make_campaign(db, factory, product)
    campaign.status = CampaignStatus.active
    campaign.sent_count = 100
    campaign.bounced_count = 8  # 8% > 5% threshold
    db.commit()

    paused = deliverability.evaluate_campaign_health(db, campaign)
    assert paused
    assert campaign.status == CampaignStatus.auto_paused
    assert "bounce" in campaign.paused_reason


def test_no_pause_below_min_volume(db, factory, product):
    campaign = make_campaign(db, factory, product)
    campaign.status = CampaignStatus.active
    campaign.sent_count = 10
    campaign.bounced_count = 5  # 50% but too few sends to judge
    db.commit()
    assert not deliverability.evaluate_campaign_health(db, campaign)
    assert campaign.status == CampaignStatus.active


def test_paused_factory_blocks_send(db, factory, product):
    factory.sends_paused = True
    factory.paused_reason = "manual hold"
    campaign = make_campaign(db, factory, product)
    assert not deliverability.can_send(db, campaign).ok

"""Locks for audit 2026-08-07 C4: no email may strand in ``queued`` silently.

Four rails, each previously missing:

1. the queue-time gate governs account-bound campaigns by the MAILBOX's
   counters (the worker's rule), not the factory-domain legacy counters;
2. a worker-side ``SendBlocked`` persists ``blocked_reason`` on the row;
3. the ``redispatch_queued_emails`` beat re-enqueues the queued backlog and
   raises one deduplicated operator notification per stuck campaign;
4. disconnecting a mailbox pauses its campaigns (with its own reason, so
   reauth auto-resume never resurrects a deliberate disconnect).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import Campaign, CampaignStatus, EmailStatus, Notification, utcnow
from app.services import approval
from app.services.approval import TransitionError
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email
from tests.test_sender_accounts import make_verified_account


def _approved_email(db, factory, product, admin_user, *, account=None, email_addr="b@x.example"):
    buyer, contact = make_buyer_with_contact(db, email=email_addr)
    campaign = make_campaign(db, factory, product)
    if account is not None:
        campaign.sender_account_id = account.id
        db.flush()
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    db.commit()
    return campaign, email


def test_queue_gate_uses_account_counters_for_account_bound_campaigns(
    db, factory, product, admin_user
):
    """A mailbox at its daily cap must refuse at QUEUE time, not strand later."""
    account = make_verified_account(db, factory, limit=1)
    account.daily_sent_count = 1  # cap reached
    db.commit()
    _campaign, email = _approved_email(db, factory, product, admin_user, account=account)

    with pytest.raises(TransitionError):
        approval.queue(db, email, admin_user)
    assert email.status != EmailStatus.queued


def test_worker_send_blocked_persists_reason(db, factory, product, admin_user, monkeypatch):
    """A blocked send leaves `queued` + a persisted, user-visible reason."""
    from app.workers import tasks as worker_tasks

    account = make_verified_account(db, factory, limit=5)
    campaign, email = _approved_email(db, factory, product, admin_user, account=account)
    approval.queue(db, email, admin_user)
    db.commit()

    # Pause the campaign after queueing: the worker's re-check must block.
    campaign.status = CampaignStatus.paused
    campaign.paused_reason = "operator pause"
    db.commit()

    out = worker_tasks.send_approved_email.apply(args=[str(email.id)], throw=False).result
    db.expire_all()
    assert out["sent"] is False
    assert email.status == EmailStatus.queued
    assert email.blocked_reason  # the row explains itself now


def test_redispatch_sweep_reenqueues_and_notifies_once(
    db, factory, product, admin_user, monkeypatch
):
    from app.workers import tasks as worker_tasks

    account = make_verified_account(db, factory, limit=5)
    campaign, email = _approved_email(db, factory, product, admin_user, account=account)
    approval.queue(db, email, admin_user)
    # Backdate far past both thresholds: eligible for redispatch AND stuck.
    email.queued_at = utcnow() - timedelta(hours=48)
    campaign.status = CampaignStatus.paused  # keeps the send blocked
    campaign.paused_reason = "operator pause"
    db.commit()

    enqueued: list[str] = []
    monkeypatch.setattr(worker_tasks.send_approved_email, "delay", lambda eid: enqueued.append(eid))

    out1 = worker_tasks.redispatch_queued_emails.apply(throw=False).result
    assert out1["redispatched"] == 1
    assert enqueued == [str(email.id)]
    assert out1["campaigns_notified"] == 1

    # Second sweep: re-enqueues again (drain keeps trying) but does NOT spam a
    # second notification while the first is unread.
    out2 = worker_tasks.redispatch_queued_emails.apply(throw=False).result
    assert out2["redispatched"] == 1
    assert out2["campaigns_notified"] == 0

    notes = db.query(Notification).filter(Notification.kind == "sends_stuck_queued").all()
    assert len(notes) == 1
    assert notes[0].entity_id == str(campaign.id)


def test_every_email_status_has_an_owner():
    """Terminal-state contract: each non-terminal EmailStatus maps to a beat owner.

    `queued` → redispatch-queued-emails; `sending` → reap-stale-sends. If a new
    non-terminal status is added without an owner, this fails.
    """
    from app.workers.celery_app import celery_app

    beats = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    owners = {
        EmailStatus.queued: "app.workers.tasks.redispatch_queued_emails",
        EmailStatus.sending: "app.workers.tasks.reap_stale_sends",
    }
    non_terminal = {
        s
        for s in EmailStatus
        if s
        not in (
            EmailStatus.draft,  # owned by the human review queue (UI)
            EmailStatus.rejected,
            EmailStatus.approved,  # owned by the human queue step (UI)
            EmailStatus.sent,
            EmailStatus.opened,
            EmailStatus.replied,
            EmailStatus.bounced,
            EmailStatus.complained,
            EmailStatus.cancelled,
            EmailStatus.blocked_suppressed,
        )
    }
    for status in non_terminal:
        assert status in owners, f"non-terminal status {status} has no beat owner"
        assert owners[status] in beats, f"beat for {status} is not scheduled"


def test_disconnect_pauses_campaigns(
    client, db, factory, factory_user, product, admin_user, auth_headers
):
    account = make_verified_account(db, factory)
    campaign, _email = _approved_email(db, factory, product, admin_user, account=account)
    campaign.status = CampaignStatus.active
    db.commit()

    headers = auth_headers
    resp = client.delete(f"/api/v1/sender-accounts/{account.id}", headers=headers)
    assert resp.status_code == 204

    db.expire_all()
    fresh = db.get(Campaign, campaign.id)
    assert fresh.status == CampaignStatus.paused
    assert "disconnected" in (fresh.paused_reason or "")
    note = (
        db.query(Notification)
        .filter(Notification.kind == "campaigns_paused_disconnect")
        .one_or_none()
    )
    assert note is not None

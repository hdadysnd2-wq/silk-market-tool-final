"""Regression locks for the two-phase send claim (audit blocker #3).

The send worker previously called the provider while the row was still ``queued``
inside an uncommitted transaction, so a worker crash or Redis redelivery between
provider-accept and commit re-sent the message. The fix claims the row
(``queued`` → ``sending``, committed) BEFORE egress, so a re-run finds ``sending``
and refuses; a reaper resolves rows stuck mid-flight without ever re-sending.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import EmailStatus, Notification, utcnow
from app.providers.base import SendResult
from app.services import approval
from app.services.sending import SendBlocked, reap_stale_sends, send_email
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _queued_email(db, factory, product, admin_user, *, email_addr="buyer@acme.example.in"):
    buyer, contact = make_buyer_with_contact(db, email=email_addr)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    db.commit()
    return campaign, email


class _RowInspectingProvider:
    """Asserts the row was committed to ``sending`` *before* the provider call."""

    name = "inspector"

    def __init__(self, db, email_id):
        self._db = db
        self._email_id = email_id
        self.calls = 0
        self.status_at_send = None

    def send(self, message):
        self.calls += 1
        from app.models import Email

        # Read the row in a fresh state: the claim must already be persisted.
        self._db.expire_all()
        self.status_at_send = self._db.get(Email, self._email_id).status
        return SendResult(accepted=True, provider_message_id="pm-1", provider_name=self.name)


def test_row_is_claimed_before_provider_call(db, factory, product, admin_user):
    _campaign, email = _queued_email(db, factory, product, admin_user)
    provider = _RowInspectingProvider(db, email.id)

    sent = send_email(db, email.id, provider)

    assert provider.calls == 1
    assert provider.status_at_send == EmailStatus.sending  # claimed before egress
    assert sent.status == EmailStatus.sent


def test_redelivered_send_does_not_double_send(db, factory, product, admin_user):
    """A row already claimed (status ``sending``) must never be sent again."""
    _campaign, email = _queued_email(db, factory, product, admin_user)
    # Simulate a crash after claim: the row is left in ``sending``.
    email.status = EmailStatus.sending
    email.claimed_at = utcnow()
    db.commit()

    class _Spy:
        name = "spy"

        def __init__(self):
            self.calls = 0

        def send(self, message):
            self.calls += 1
            return SendResult(accepted=True, provider_message_id="x", provider_name="spy")

    spy = _Spy()
    with pytest.raises(SendBlocked):
        send_email(db, email.id, spy)
    assert spy.calls == 0  # provider never touched


def test_rejected_send_is_requeued(db, factory, product, admin_user):
    _campaign, email = _queued_email(db, factory, product, admin_user)

    class _Rejecter:
        name = "rejecter"

        def send(self, message):
            return SendResult(
                accepted=False, provider_message_id=None, provider_name="rejecter", error="nope"
            )

    with pytest.raises(SendBlocked):
        send_email(db, email.id, _Rejecter())

    db.expire_all()
    from app.models import Email

    refreshed = db.get(Email, email.id)
    assert refreshed.status == EmailStatus.queued  # safe to retry — never sent
    assert refreshed.claimed_at is None


def test_reaper_cancels_stale_claim_and_notifies(db, factory, product, admin_user):
    _campaign, email = _queued_email(db, factory, product, admin_user)
    # A send claimed 20 minutes ago but never resolved (worker was lost).
    email.status = EmailStatus.sending
    email.claimed_at = utcnow() - timedelta(minutes=20)
    db.commit()

    reaped = reap_stale_sends(db, stale_seconds=900)
    db.commit()

    assert reaped == 1
    db.expire_all()
    from app.models import Email

    refreshed = db.get(Email, email.id)
    assert refreshed.status == EmailStatus.cancelled
    assert "double-send" in (refreshed.blocked_reason or "")
    # The interrupted send is surfaced, not silently lost.
    from sqlalchemy import select

    note = db.scalar(select(Notification).where(Notification.kind == "send_interrupted"))
    assert note is not None


def test_reaper_leaves_fresh_claims_untouched(db, factory, product, admin_user):
    _campaign, email = _queued_email(db, factory, product, admin_user)
    email.status = EmailStatus.sending
    email.claimed_at = utcnow()  # just claimed
    db.commit()

    assert reap_stale_sends(db, stale_seconds=900) == 0
    db.expire_all()
    from app.models import Email

    assert db.get(Email, email.id).status == EmailStatus.sending

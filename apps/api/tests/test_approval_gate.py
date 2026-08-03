"""The approval gate — the platform's hardest requirement.

These tests pin the guarantee that no email is ever sent without an explicit
human approval, across all three enforcement layers.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog, EmailStatus
from app.security import create_access_token
from app.services import approval
from app.services.sending import SendBlocked, send_email
from tests.conftest import (
    make_buyer_with_contact,
    make_campaign,
    make_draft_email,
)


def test_queue_rejected_when_draft(db, factory, product, admin_user):
    """A draft cannot be queued — it must be approved first."""
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    with pytest.raises(approval.TransitionError):
        approval.queue(db, email, admin_user)

    db.refresh(email)
    assert email.status == EmailStatus.draft


def test_send_task_refuses_unapproved(db, factory, product):
    """The send path never calls the provider for an unapproved email."""
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    spy = MagicMock()
    with pytest.raises(SendBlocked):
        send_email(db, email.id, spy)

    spy.send.assert_not_called()
    db.refresh(email)
    assert email.status == EmailStatus.draft


def test_db_constraint_blocks_sent_without_approval(db, factory, product):
    """Even a raw UPDATE can't set a sent-family status without an approver."""
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    with pytest.raises(IntegrityError):
        db.execute(
            text("UPDATE emails SET status = 'sent' WHERE id = :id AND approved_at IS NULL"),
            {"id": str(email.id)},
        )
        db.flush()
    db.rollback()


def test_approve_writes_approver_and_audit(db, factory, product, admin_user):
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    approval.approve(db, email, admin_user)
    db.commit()

    db.refresh(email)
    assert email.status == EmailStatus.approved
    assert email.approved_by == admin_user.id
    assert email.approved_at is not None

    entry = db.query(AuditLog).filter(AuditLog.action == "approve_email").one()
    assert entry.entity_id == str(email.id)
    assert entry.actor_user_id == admin_user.id


def test_full_approval_flow_reaches_sent(db, factory, product, admin_user):
    """Approve → queue → send succeeds and calls the provider exactly once."""
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    db.commit()

    provider = MagicMock()
    provider.send.return_value = _accepted_send_result()
    sent = send_email(db, email.id, provider)

    provider.send.assert_called_once()
    assert sent.status == EmailStatus.sent
    assert sent.provider_message_id == "prov-123"


def test_edit_after_approval_requires_reapproval(db, factory, product, admin_user):
    """Reverting an approved email to draft clears the approval."""
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    approval.approve(db, email, admin_user)
    approval.revert_to_draft(db, email, admin_user)
    db.commit()

    db.refresh(email)
    assert email.status == EmailStatus.draft
    assert email.approved_at is None
    assert email.approved_by is None


def test_followup_starts_as_draft_and_cannot_send(db, factory, product, admin_user):
    """A follow-up is a fresh draft — it goes through its own approval."""
    from app.models import Email

    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    followup = Email(
        campaign_id=campaign.id,
        contact_id=contact.id,
        buyer_id=buyer.id,
        status=EmailStatus.draft,
        subject="Re: Hello",
        body_text="Follow up",
        language="en",
        unsubscribe_token=uuid.uuid4().hex,
        is_followup=True,
        followup_number=1,
    )
    db.add(followup)
    db.commit()

    spy = MagicMock()
    with pytest.raises(SendBlocked):
        send_email(db, followup.id, spy)
    spy.send.assert_not_called()


def test_cross_factory_approval_forbidden(db, factory, product, market):
    """A factory user cannot approve another factory's email (API 403)."""
    from app.models import Factory, User, UserRole
    from app.security import hash_password

    other_factory = Factory(name_ar="آخر", name_en="Other Factory")
    db.add(other_factory)
    db.flush()
    other_user = User(
        email="other@x.com",
        password_hash=hash_password("Passw0rd!"),
        role=UserRole.factory_user,
        factory_id=other_factory.id,
    )
    db.add(other_user)

    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)
    db.commit()

    from fastapi.testclient import TestClient

    from app.main import app

    token = create_access_token(other_user.id, other_user.role)
    resp = TestClient(app).post(
        f"/api/v1/emails/{email.id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def _accepted_send_result():
    from app.providers.base import SendResult

    return SendResult(accepted=True, provider_message_id="prov-123", provider_name="mock")

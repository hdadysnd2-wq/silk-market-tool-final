"""Multi-tenant sender accounts.

Covers the guarantees the feature rests on — all against the deterministic mock
mailbox provider (no Google/Microsoft app needed):

* tenant isolation (a factory only sees/acts on its own mailboxes),
* the campaign hard-prerequisite (no verified mailbox → no campaign),
* per-account daily limits and warm-up ramp,
* suppression enforced at send time (last gate before egress),
* token revocation → pause campaigns + needs_reauth + notification,
* reply detection → stop the contact's sequence + notify,
* token encryption at rest.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.crypto import decrypt, encrypt
from app.models import (
    AuditLog,
    CampaignStatus,
    Email,
    EmailStatus,
    Factory,
    Notification,
    SenderAccount,
    SenderProviderType,
    SenderVerificationStatus,
    SuppressionReason,
    User,
    UserRole,
    utcnow,
)
from app.providers.base import MailboxCredentials, ReplyMessage
from app.security import create_access_token, hash_password
from app.services import approval, replies, sender_accounts, sender_oauth, suppression
from app.services.sending import AccountBoundSender, SendBlocked, send_email
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email

# -- helpers ---------------------------------------------------------------


def make_verified_account(
    db,
    factory,
    *,
    provider: str = "mock",
    email: str = "mailbox@factory.example",
    stage: int = 1,
    limit: int = 50,
    access: str | None = "mock-access",
    refresh: str | None = "mock-refresh",
    expires_in: int = 3600,
) -> SenderAccount:
    account = SenderAccount(
        factory_id=factory.id,
        email=email,
        provider_type=SenderProviderType(provider),
        verification_status=SenderVerificationStatus.verified,
        verified_at=utcnow(),
        warmup_stage=stage,
        warmup_started_at=utcnow(),
        daily_send_limit=limit,
        daily_sent_count=0,
        daily_counter_date=utcnow(),
        access_token_encrypted=encrypt(access),
        refresh_token_encrypted=encrypt(refresh),
        token_expires_at=utcnow() + timedelta(seconds=expires_in),
        scopes="mailbox.send mailbox.read",
    )
    db.add(account)
    db.commit()
    return account


def _second_factory_user(db) -> tuple[Factory, User]:
    other = Factory(name_ar="آخر", name_en="Other Factory")
    db.add(other)
    db.flush()
    user = User(
        email="other-sender@x.com",
        password_hash=hash_password("Passw0rd!"),
        role=UserRole.factory_user,
        factory_id=other.id,
    )
    db.add(user)
    db.commit()
    return other, user


# -- token encryption ------------------------------------------------------


def test_token_crypto_roundtrip_never_plaintext():
    secret = "1//refresh-token-abc123"
    ciphertext = encrypt(secret)
    assert ciphertext is not None
    assert secret not in ciphertext  # never stored in the clear
    assert decrypt(ciphertext) == secret
    assert encrypt(None) is None
    assert decrypt(None) is None


# -- OAuth connect flow (mock) --------------------------------------------


def test_oauth_connect_flow_verifies_and_activates(client, db, factory, factory_user):
    token = create_access_token(factory_user.id, factory_user.role)
    headers = {"Authorization": f"Bearer {token}"}

    initiated = client.post("/api/v1/sender-accounts/connect/gmail", headers=headers)
    assert initiated.status_code == 200
    url = initiated.json()["authorization_url"]

    qs = parse_qs(urlparse(url).query)
    callback = client.get(
        "/api/v1/sender-accounts/callback/gmail",
        params={"code": qs["code"][0], "state": qs["state"][0]},
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert "connected=1" in callback.headers["location"]

    listed = client.get("/api/v1/sender-accounts", headers=headers)
    assert listed.status_code == 200
    accounts = listed.json()
    assert len(accounts) == 1
    assert accounts[0]["verification_status"] == "verified"
    assert accounts[0]["provider_type"] == "gmail"
    # The response never leaks tokens.
    assert "access_token" not in accounts[0]
    assert "refresh_token_encrypted" not in accounts[0]


def test_callback_rejects_tampered_state(client, db, factory, factory_user):
    resp = client.get(
        "/api/v1/sender-accounts/callback/gmail",
        params={"code": "x", "state": "not-a-valid-jwt"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=invalid_state" in resp.headers["location"]
    assert db.scalar(select(SenderAccount)) is None


# -- tenant isolation ------------------------------------------------------


def test_sender_accounts_scoped_to_factory(client, db, factory, factory_user):
    make_verified_account(db, factory, email="mine@factory.example")
    other_factory, _ = _second_factory_user(db)
    make_verified_account(db, other_factory, email="theirs@other.example")

    token = create_access_token(factory_user.id, factory_user.role)
    resp = client.get("/api/v1/sender-accounts", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    emails = {a["email"] for a in resp.json()}
    assert emails == {"mine@factory.example"}


def test_cross_factory_sender_account_forbidden(client, db, factory, factory_user):
    other_factory, _ = _second_factory_user(db)
    victim = make_verified_account(db, other_factory, email="victim@other.example")

    token = create_access_token(factory_user.id, factory_user.role)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.delete(f"/api/v1/sender-accounts/{victim.id}", headers=headers).status_code == 403
    assert (
        client.post(f"/api/v1/sender-accounts/{victim.id}/reconnect", headers=headers).status_code
        == 403
    )


# -- campaign hard prerequisite -------------------------------------------


def test_campaign_blocked_without_verified_sender(
    client, db, factory, product, factory_user, market
):
    token = create_access_token(factory_user.id, factory_user.role)
    headers = {"Authorization": f"Bearer {token}"}
    body = {"product_id": str(product.id), "market_iso2": "IN", "name": "Outreach"}

    blocked = client.post("/api/v1/campaigns", headers=headers, json=body)
    assert blocked.status_code == 412

    account = make_verified_account(db, factory)
    created = client.post("/api/v1/campaigns", headers=headers, json=body)
    assert created.status_code == 201
    assert created.json()["sender_account_id"] == str(account.id)


# -- per-account governance -----------------------------------------------


def test_warmup_ramp_and_limits(db, factory):
    account = make_verified_account(db, factory, stage=1, limit=50)
    # A brand-new account starts warm at 10–20/day.
    assert 10 <= sender_accounts.warmup_limit(account) <= 20
    account.warmup_stage = 2
    assert sender_accounts.warmup_limit(account) == 25
    # Late stages are capped by the account's own daily limit.
    account.warmup_stage = 8
    assert sender_accounts.warmup_limit(account) == 50

    account.warmup_stage = 1
    for _ in range(sender_accounts.MAX_WARMUP_STAGE + 3):
        sender_accounts.advance_warmup(db, account)
    assert account.warmup_stage == sender_accounts.MAX_WARMUP_STAGE


def test_per_account_daily_limit_blocks_send(db, factory, product, admin_user):
    account = make_verified_account(db, factory, stage=1)  # warm-up cap 15
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    db.commit()
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    account.daily_sent_count = sender_accounts.warmup_limit(account)
    account.daily_counter_date = utcnow()
    db.commit()

    spy = MagicMock()
    with pytest.raises(SendBlocked):
        send_email(db, email.id, spy)
    spy.send.assert_not_called()


def test_account_send_happy_path_increments_account_counter(
    db, factory, product, admin_user, tmp_path
):
    from app.providers.sending.mock import MockMailboxProvider

    account = make_verified_account(db, factory)
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    db.commit()
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    db.commit()

    creds = MailboxCredentials(
        email=account.email,
        access_token="mock-access",
        refresh_token=None,
        token_expires_at=utcnow() + timedelta(hours=1),
    )
    sender = AccountBoundSender(
        MockMailboxProvider(provider_type="mock", outbox_dir=str(tmp_path)), creds
    )
    sent = send_email(db, email.id, sender)
    assert sent.status == EmailStatus.sent
    db.refresh(account)
    assert account.daily_sent_count == 1


def test_suppression_blocks_account_send_at_send_time(db, factory, product, admin_user):
    """Suppression is the final gate before egress even on the per-account path."""
    account = make_verified_account(db, factory)
    buyer, contact = make_buyer_with_contact(db, email="opt-out@acme.example.in")
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    db.commit()
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    db.commit()

    # Opt-out arrives after queueing — the classic race.
    suppression.suppress(db, email=contact.email, reason=SuppressionReason.unsubscribe)
    db.commit()

    spy = MagicMock()
    result = send_email(db, email.id, spy)
    spy.send.assert_not_called()
    assert result.status == EmailStatus.blocked_suppressed


# -- token revocation handling --------------------------------------------


def test_token_revocation_pauses_campaigns_and_notifies(db, factory, product):
    account = make_verified_account(db, factory, refresh="mock-refresh.revoked")
    account.token_expires_at = utcnow() - timedelta(hours=1)  # force a refresh
    db.commit()
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    campaign.status = CampaignStatus.active
    db.commit()

    with pytest.raises(sender_oauth.ReauthRequired):
        sender_oauth.ensure_valid_credentials(db, account)

    db.refresh(account)
    assert account.verification_status == SenderVerificationStatus.needs_reauth
    assert account.reauth_reason

    db.refresh(campaign)
    assert campaign.status == CampaignStatus.paused
    assert campaign.paused_reason == sender_oauth.REAUTH_PAUSE_REASON

    note = db.scalar(select(Notification).where(Notification.kind == "mailbox_needs_reauth"))
    assert note is not None and note.factory_id == factory.id
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "sender_needs_reauth"))
    assert entry is not None


def test_needs_reauth_account_cannot_send(db, factory, product, admin_user):
    account = make_verified_account(db, factory)
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    db.commit()
    email = make_draft_email(db, campaign, buyer, contact)
    approval.approve(db, email, admin_user)
    approval.queue(db, email, admin_user)
    account.verification_status = SenderVerificationStatus.needs_reauth
    db.commit()

    spy = MagicMock()
    with pytest.raises(SendBlocked):
        send_email(db, email.id, spy)
    spy.send.assert_not_called()


def test_reconnect_resumes_reauth_paused_campaigns(db, factory, product, factory_user):
    account = make_verified_account(db, factory, refresh="mock-refresh.revoked")
    account.token_expires_at = utcnow() - timedelta(hours=1)
    db.commit()
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    campaign.status = CampaignStatus.active
    db.commit()

    with pytest.raises(sender_oauth.ReauthRequired):
        sender_oauth.ensure_valid_credentials(db, account)
    db.refresh(campaign)
    assert campaign.status == CampaignStatus.paused

    # Reconnect through the (mock) OAuth flow with the same mailbox.
    url = sender_oauth.initiate_connect(
        db, factory=factory, provider_type="mock", user=factory_user, account=account
    )
    qs = parse_qs(urlparse(url).query)
    sender_oauth.complete_callback(
        db, provider_type="mock", code=qs["code"][0], state=qs["state"][0]
    )

    db.refresh(account)
    assert account.verification_status == SenderVerificationStatus.verified
    db.refresh(campaign)
    assert campaign.status == CampaignStatus.active


# -- reply detection & sequence stop --------------------------------------


def _make_sent_email(db, campaign, buyer, contact, admin_user) -> Email:
    email = Email(
        campaign_id=campaign.id,
        contact_id=contact.id,
        buyer_id=buyer.id,
        status=EmailStatus.sent,
        subject="Intro",
        body_text="Hello",
        language="en",
        unsubscribe_token=uuid.uuid4().hex,
        approved_by=admin_user.id,
        approved_at=utcnow(),
        sent_at=utcnow(),
    )
    db.add(email)
    db.commit()
    return email


def test_reply_stops_sequence_and_notifies(db, factory, product, admin_user):
    account = make_verified_account(db, factory)
    buyer, contact = make_buyer_with_contact(db, email="prospect@acme.example.in")
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    db.commit()
    sent = _make_sent_email(db, campaign, buyer, contact, admin_user)
    followup = make_draft_email(db, campaign, buyer, contact)  # pending sequence step

    reply = ReplyMessage(
        from_email="PROSPECT@acme.example.in",  # different casing on purpose
        to_email=account.email,
        subject="Re: Intro",
        received_at=utcnow(),
        provider_message_id="reply-1",
    )
    matched = replies.handle_reply(db, account, reply)
    assert matched is True

    db.refresh(sent)
    assert sent.status == EmailStatus.replied
    db.refresh(followup)
    assert followup.status == EmailStatus.cancelled  # sequence stopped

    assert db.scalar(select(Notification).where(Notification.kind == "reply_received")) is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "reply_received")) is not None


def test_poll_account_matches_replies_via_provider(db, factory, product, admin_user):
    account = make_verified_account(db, factory)
    buyer, contact = make_buyer_with_contact(db, email="p2@acme.example.in")
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    db.commit()
    _make_sent_email(db, campaign, buyer, contact, admin_user)

    class FakeProvider:
        def fetch_replies(self, creds, since):
            return [
                ReplyMessage(
                    from_email="p2@acme.example.in",
                    to_email=account.email,
                    subject="Re",
                    received_at=utcnow(),
                    provider_message_id="x",
                )
            ]

    creds = MailboxCredentials(email=account.email, access_token="x")
    matched = replies.poll_account(db, account, FakeProvider(), creds, utcnow() - timedelta(days=1))
    assert matched == 1
    db.refresh(account)
    assert account.last_polled_at is not None


def test_reply_from_unknown_address_is_ignored(db, factory, product, admin_user):
    account = make_verified_account(db, factory)
    buyer, contact = make_buyer_with_contact(db, email="known@acme.example.in")
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    db.commit()
    _make_sent_email(db, campaign, buyer, contact, admin_user)

    stranger = ReplyMessage(
        from_email="stranger@nowhere.example",
        to_email=account.email,
        subject="Re",
        received_at=utcnow(),
        provider_message_id="s1",
    )
    assert replies.handle_reply(db, account, stranger) is False

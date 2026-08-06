"""Regression locks for connected-mailbox bounce detection (audit blocker #2).

Mailbox (Gmail/Microsoft) sends receive no provider webhook, so a hard bounce
arrives only as an NDR in the inbox. Before this fix the reply poller matched
inbound mail by the *contact's* address, so mailer-daemon/postmaster NDRs never
matched: bounced_count stayed 0, dead addresses were never suppressed, and the
5% bounce auto-pause guardrail could never fire on the primary send path.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import EmailStatus
from app.providers.base import ReplyMessage
from app.providers.sending.gmail_oauth import GmailOAuthProvider
from app.providers.sending.microsoft_oauth import MicrosoftGraphProvider
from app.services import replies, suppression
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email
from tests.test_sender_accounts import make_verified_account


def _mark_sent(db, email):
    # The DB CHECK constraint (ck_emails_sent_requires_approval) requires an
    # approval timestamp before an email can enter the sent family.
    email.approved_at = datetime.now(UTC)
    email.approved_by_label = "test-approver"
    email.status = EmailStatus.sent
    email.sent_at = datetime.now(UTC)
    db.commit()


def _sent_email(db, factory, product, *, email_addr, account):
    buyer, contact = make_buyer_with_contact(db, email=email_addr)
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    campaign.sent_count = 25  # over the auto-pause minimum volume
    e = make_draft_email(db, campaign, buyer, contact)
    _mark_sent(db, e)
    return campaign, contact, e


def _ndr(failed: str, sender: str = "mailer-daemon@googlemail.com") -> ReplyMessage:
    return ReplyMessage(
        from_email=sender,
        to_email="mailbox@factory.example",
        subject="Delivery Status Notification (Failure)",
        received_at=datetime.now(UTC),
        provider_message_id="ndr-1",
        failed_recipient=failed,
    )


def test_ndr_marks_email_bounced_and_suppresses(db, factory, product):
    account = make_verified_account(db, factory)
    campaign, contact, email = _sent_email(
        db, factory, product, email_addr="dead@acme.example.in", account=account
    )

    matched = replies.handle_bounce(db, account, _ndr("dead@acme.example.in"))

    assert matched is True
    db.refresh(email)
    db.refresh(campaign)
    assert email.status == EmailStatus.bounced
    assert email.bounced_at is not None
    assert campaign.bounced_count == 1
    assert suppression.is_suppressed(db, contact.email)


def test_ndr_is_idempotent(db, factory, product):
    account = make_verified_account(db, factory)
    campaign, _contact, email = _sent_email(
        db, factory, product, email_addr="dead2@acme.example.in", account=account
    )
    ndr = _ndr("dead2@acme.example.in")

    assert replies.handle_bounce(db, account, ndr) is True
    assert replies.handle_bounce(db, account, ndr) is False  # already bounced
    db.refresh(campaign)
    assert campaign.bounced_count == 1


def test_high_bounce_rate_auto_pauses_on_mailbox_path(db, factory, product):
    """The guardrail the finding says is inert on the mailbox path must fire."""
    from app.models import CampaignStatus

    account = make_verified_account(db, factory)
    campaign = make_campaign(db, factory, product)
    campaign.sender_account_id = account.id
    campaign.sent_count = 20
    db.commit()

    # Two distinct sent emails; bounce both -> 10% > 5% threshold.
    for i, market in enumerate(("US", "GB")):
        _b, c = make_buyer_with_contact(db, market_iso2=market, email=f"bounce{i}@acme.example.in")
        e = make_draft_email(db, campaign, _b, c)
        _mark_sent(db, e)
        replies.handle_bounce(db, account, _ndr(f"bounce{i}@acme.example.in"))

    db.refresh(campaign)
    assert campaign.status == CampaignStatus.auto_paused


def test_reply_and_bounce_are_split_in_poll(db, factory, product):
    """poll_account routes an NDR to the bounce path, a human reply to replies."""
    account = make_verified_account(db, factory)
    _c, _contact, bounced = _sent_email(
        db, factory, product, email_addr="gone@acme.example.in", account=account
    )
    replier_buyer, replier_contact = make_buyer_with_contact(
        db, market_iso2="US", email="human@acme.example.in"
    )
    campaign2 = make_campaign(db, factory, product)
    campaign2.sender_account_id = account.id
    reply_email = make_draft_email(db, campaign2, replier_buyer, replier_contact)
    _mark_sent(db, reply_email)

    human_reply = ReplyMessage(
        from_email="human@acme.example.in",
        to_email="mailbox@factory.example",
        subject="Re: your note",
        received_at=datetime.now(UTC),
        provider_message_id="r-1",
    )

    class _FakeProvider:
        def fetch_replies(self, creds, since):
            return [_ndr("gone@acme.example.in"), human_reply]

    matched = replies.poll_account(
        db, account, _FakeProvider(), creds=None, since=datetime.now(UTC)
    )

    assert matched == 1  # only the human reply counts as a reply
    db.refresh(bounced)
    db.refresh(reply_email)
    assert bounced.status == EmailStatus.bounced
    assert reply_email.status == EmailStatus.replied


def test_human_reply_is_never_classified_as_bounce():
    human = ReplyMessage(
        from_email="postmaster@acme.example.in",  # machine-looking, but no NDR field
        to_email="x@y.z",
        subject="out of office",
        received_at=datetime.now(UTC),
        provider_message_id="r-2",
    )
    assert replies.is_bounce(human) is False


def test_gmail_parses_failed_recipient_header():
    payload = {
        "id": "g1",
        "payload": {
            "headers": [
                {"name": "From", "value": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"},
                {"name": "To", "value": "mailbox@factory.example"},
                {"name": "Subject", "value": "Delivery Status Notification (Failure)"},
                {"name": "X-Failed-Recipients", "value": "nobody@dead-domain.example"},
            ]
        },
    }
    reply = GmailOAuthProvider._parse_reply(payload)
    assert reply is not None
    assert reply.failed_recipient == "nobody@dead-domain.example"
    assert replies.is_bounce(reply) is True


def test_microsoft_parses_failed_recipient_from_body_preview():
    msg = {
        "id": "m1",
        "from": {"emailAddress": {"address": "postmaster@factory.example"}},
        "toRecipients": [{"emailAddress": {"address": "mailbox@factory.example"}}],
        "subject": "Undeliverable: Quote",
        "bodyPreview": "Your message to nobody@dead-domain.example couldn't be delivered.",
    }
    reply = MicrosoftGraphProvider._parse_reply(msg)
    assert reply is not None
    assert reply.failed_recipient == "nobody@dead-domain.example"
    assert replies.is_bounce(reply) is True

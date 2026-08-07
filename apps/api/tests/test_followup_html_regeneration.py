"""Lock the follow-up HTML/token fix (audit 2026-08-07 L3).

Auto-created follow-up drafts used to copy the parent's ``body_html`` verbatim
while only ``body_text`` got the follow-up intro — so the HTML MIME part lacked
the intro and still embedded the PARENT's unsubscribe token. Both parts must now
carry the follow-up content and the row's OWN token.
"""

from __future__ import annotations

from datetime import timedelta

from app.models import Email, EmailStatus, utcnow
from app.services.email_drafting import unsubscribe_url
from app.workers import tasks
from tests.conftest import make_buyer_with_contact, make_campaign


def _sent(db, campaign, buyer, contact, *, days_ago: int) -> Email:
    email = Email(
        campaign_id=campaign.id,
        contact_id=contact.id,
        buyer_id=buyer.id,
        status=EmailStatus.sent,
        subject="Original subject",
        body_text="Original body text.",
        body_html="<p>Original body text.</p>",
        language="en",
        sent_at=utcnow() - timedelta(days=days_ago),
        approved_by_label="approver@silk",
        approved_at=utcnow() - timedelta(days=days_ago),
        unsubscribe_token="PARENT-TOKEN-should-not-leak",
    )
    db.add(email)
    db.commit()
    return email


def test_followup_html_carries_intro_and_own_token(db, factory, product):
    campaign = make_campaign(db, factory, product)
    buyer, contact = make_buyer_with_contact(db, email="lead@acme.example.in")
    parent = _sent(db, campaign, buyer, contact, days_ago=5)

    assert tasks.process_followups.apply().result == {"followup_drafts_created": 1}

    followup = (
        db.query(Email)
        .filter(Email.parent_email_id == parent.id, Email.is_followup.is_(True))
        .one()
    )
    # Its own token, not the parent's.
    assert followup.unsubscribe_token != parent.unsubscribe_token
    assert "PARENT-TOKEN" not in (followup.body_html or "")
    # The HTML part carries the follow-up intro (regenerated from the text), not
    # a byte-identical copy of the parent HTML.
    assert followup.body_html != parent.body_html
    assert "follow up" in followup.body_text.lower()
    # The HTML embeds the follow-up row's own unsubscribe URL.
    assert unsubscribe_url(followup.unsubscribe_token) in followup.body_html

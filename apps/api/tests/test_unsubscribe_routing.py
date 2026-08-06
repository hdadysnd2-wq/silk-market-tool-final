"""Regression locks for the unsubscribe money path (audit 2026-08-06, blocker #1).

Two defects are locked here:

1. The generated unsubscribe URL must target the API origin. It previously used
   ``app_base_url`` (the Next.js web origin), which serves no ``/u`` route and
   proxies only ``/api/v1/*`` — every recipient's opt-out link (and the RFC 8058
   ``List-Unsubscribe`` headers built from the same URL) 404'd.
2. The GET confirmation page must not reflect the attacker-controlled token into
   its HTML (reflected XSS via a crafted ``/u/<payload>`` link).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.config import get_settings
from app.services.email_drafting import unsubscribe_url
from app.services.suppression import is_suppressed
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def test_unsubscribe_url_targets_api_origin():
    url = unsubscribe_url("tok-abc")
    settings = get_settings()
    assert url == f"{settings.api_base_url.rstrip('/')}/u/tok-abc"
    # The web origin must never appear: it cannot route /u.
    assert not url.startswith(settings.app_base_url.rstrip("/"))


def test_generated_unsubscribe_url_resolves_get_and_post(db, factory, product, admin_user, client):
    """The exact URL we put in outbound mail must resolve on the app that serves it."""
    buyer, contact = make_buyer_with_contact(db, email="optout-route@acme.example.in")
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)
    db.commit()

    path = urlsplit(unsubscribe_url(email.unsubscribe_token)).path

    # GET renders the confirmation page and never mutates.
    resp = client.get(path)
    assert resp.status_code == 200
    assert not is_suppressed(db, contact.email)

    # POST (RFC 8058 one-click / the form button) performs the unsubscribe.
    resp = client.post(path)
    assert resp.status_code == 200
    db.expire_all()
    assert is_suppressed(db, contact.email)


def test_unsubscribe_form_does_not_reflect_token(client):
    payload = '"><img src=x onerror=alert(1)>'
    resp = client.get("/u/" + payload)
    assert resp.status_code == 200
    assert "onerror" not in resp.text
    assert payload not in resp.text

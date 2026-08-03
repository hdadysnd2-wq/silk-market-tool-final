"""Regression tests for the code-review findings."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.models import EmailStatus, Shipment, SuppressionReason, utcnow
from app.services import suppression
from app.services.buyer_discovery import _score
from app.services.email_drafting import ensure_compliance_footer, render_html_body
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email

# --- Fix: webhook signature verification ----------------------------------


def test_webhook_requires_valid_signature_when_secret_set(client, monkeypatch):
    import app.api.webhooks as webhooks

    monkeypatch.setattr(
        webhooks, "get_settings", lambda: SimpleNamespace(smartlead_webhook_secret="s3cr3t")
    )
    body = json.dumps({"event": "opened", "message_id": "mock-x"}).encode()

    # Unsigned → rejected.
    unsigned = client.post(
        "/api/v1/webhooks/smartlead",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert unsigned.status_code == 401

    # Correctly signed → accepted (no matching email, but authenticated).
    sig = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    signed = client.post(
        "/api/v1/webhooks/smartlead",
        content=body,
        headers={"Content-Type": "application/json", "X-Smartlead-Signature": sig},
    )
    assert signed.status_code == 200


def test_webhook_open_when_no_secret_configured(client, monkeypatch):
    import app.api.webhooks as webhooks

    monkeypatch.setattr(
        webhooks, "get_settings", lambda: SimpleNamespace(smartlead_webhook_secret="")
    )
    resp = client.post(
        "/api/v1/webhooks/smartlead", json={"event": "opened", "message_id": "mock-none"}
    )
    assert resp.status_code == 200


# --- Fix: unsubscribe is POST-only (GET must not mutate state) -------------


def test_unsubscribe_get_does_not_suppress(client, db, factory, product):
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    resp = client.get(f"/u/{email.unsubscribe_token}")
    assert resp.status_code == 200  # renders a confirm form
    assert not suppression.is_suppressed(db, contact.email)


def test_unsubscribe_post_suppresses(client, db, factory, product):
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    resp = client.post(f"/u/{email.unsubscribe_token}")
    assert resp.status_code == 200
    assert suppression.is_suppressed(db, contact.email)


# --- Fix: edit_email regenerates body_html --------------------------------


def test_edit_email_regenerates_html(client, db, factory, product, auth_headers):
    buyer, contact = make_buyer_with_contact(db)
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)
    email.body_html = "<div>STALE ORIGINAL</div>"
    db.commit()

    resp = client.put(
        f"/api/v1/emails/{email.id}",
        json={"body_text": "Fresh corrected body"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    db.refresh(email)
    assert "Fresh corrected body" in email.body_html
    assert "STALE ORIGINAL" not in email.body_html


# --- Fix: compliance footer keys on the postal address, not just the name --


def test_compliance_footer_added_when_address_missing(factory):
    # Body names the company but omits the required physical postal address.
    body = f"Hello from {factory.name_en}. Great to connect."
    result = ensure_compliance_footer(body, factory, "en", "https://x/u/tok")
    assert factory.postal_address in result


# --- Fix: Hindi is left-to-right ------------------------------------------


def test_hindi_html_is_ltr():
    assert 'dir="ltr"' in render_html_body("नमस्ते", "tok", "hi")
    assert 'dir="rtl"' in render_html_body("مرحبا", "tok", "ar")


# --- Fix: scoring uses the real date; future shipment can't exceed max -----


def test_recency_not_inflated_by_future_shipment(db, factory, product):
    buyer, _ = make_buyer_with_contact(db)
    db.add(
        Shipment(
            buyer_id=buyer.id,
            raw_consignee_name=buyer.name,
            hs_code=product.hs_code,
            origin_iso2="CN",
            dest_iso2="IN",
            shipment_date=utcnow().date() + timedelta(days=30),  # future
            value_usd=50_000,
            quantity=1000,
            quantity_unit="kg",
            source=buyer.source,
            provider_name="test",
            source_confidence=0.85,
        )
    )
    db.commit()

    _score(db, product, buyer, "IN")
    db.commit()

    from app.models import ProductBuyerMatch

    match = db.scalar(select(ProductBuyerMatch).where(ProductBuyerMatch.buyer_id == buyer.id))
    recency = match.score_breakdown["factors"]["recency"]
    assert recency["points"] <= recency["max"]


# --- Fix: suppression cancels drafts despite un-normalized stored email ----


def test_cancel_matches_unnormalized_contact_email(db, factory, product):
    # Contact stored with mixed case + trailing space, as other sources may.
    buyer, contact = make_buyer_with_contact(db, email="John@X.com ")
    campaign = make_campaign(db, factory, product)
    email = make_draft_email(db, campaign, buyer, contact)

    suppression.suppress(db, email="john@x.com", reason=SuppressionReason.unsubscribe)
    db.commit()

    db.refresh(email)
    assert email.status == EmailStatus.cancelled


# --- Fix: authenticate always runs a password verify (no timing oracle) ----


def test_authenticate_verifies_even_for_missing_user(db, monkeypatch):
    import app.services.auth_service as auth_service

    calls: list[str] = []

    def spy(raw, hashed):
        calls.append(hashed)
        return False

    monkeypatch.setattr(auth_service, "verify_password", spy)

    with contextlib.suppress(Exception):
        auth_service.authenticate(db, email="nobody@nowhere.test", password="whatever")

    # A bcrypt verify ran on the miss path (against the dummy hash).
    assert calls and calls[0] == auth_service._DUMMY_PASSWORD_HASH


# --- Fix: comtrade excludes the World aggregate row ------------------------


def test_top_exporters_excludes_world_aggregate(monkeypatch):
    from app.providers.shipments.comtrade import ComtradeProvider

    provider = ComtradeProvider(offline=True)
    # partnerCode "0" is the World total; 156=China, 792=Türkiye.
    rows = {
        "data": [
            {"refYear": 2025, "partnerCode": "0", "primaryValue": 1000.0},
            {"refYear": 2025, "partnerCode": "156", "primaryValue": 600.0},
            {"refYear": 2025, "partnerCode": "792", "primaryValue": 400.0},
        ]
    }
    monkeypatch.setattr(provider, "_fetch", lambda hs, iso2: rows)

    exporters = provider.top_exporters("392010", "IN", limit=10)
    # World must not appear, and shares are over the real 1000 total (60% + 40%).
    assert {e.data.exporter_iso2 for e in exporters} == {"CN", "TR"}
    assert abs(sum(e.data.share_pct for e in exporters) - 100) < 0.01

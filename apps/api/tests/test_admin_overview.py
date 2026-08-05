"""B1 — GET /admin/overview: staff-only cross-tenant aggregates."""

from __future__ import annotations

from app.models import CampaignStatus
from app.security import create_access_token
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _staff_headers(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def test_factory_user_cannot_read_overview(client, auth_headers):
    res = client.get("/api/v1/admin/overview", headers=auth_headers)
    assert res.status_code == 403, res.text


def test_staff_overview_aggregates(client, db, factory, product, admin_user):
    # Two campaigns: one active, one paused — only the active one counts.
    active = make_campaign(db, factory, product)
    active.status = CampaignStatus.active
    active.sent_count = 100
    active.bounced_count = 5
    active.complained_count = 2
    paused = make_campaign(db, factory, product)
    paused.status = CampaignStatus.paused
    paused.sent_count = 100
    paused.bounced_count = 0
    paused.complained_count = 0
    db.commit()

    # Two draft emails across distinct buyers = two pending approvals. The buyer
    # builder hardcodes the name (unique per country), so use two countries.
    b1, c1 = make_buyer_with_contact(db, market_iso2="IN", email="a@buyer.example.in")
    b2, c2 = make_buyer_with_contact(db, market_iso2="AE", email="b@buyer.example.ae")
    make_draft_email(db, active, b1, c1)
    make_draft_email(db, active, b2, c2)

    res = client.get("/api/v1/admin/overview", headers=_staff_headers(admin_user))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["factories"] == 1
    assert body["active_campaigns"] == 1
    assert body["pending_approvals"] == 2
    assert body["total_sent"] == 200  # summed across both campaigns
    assert body["bounce_rate"] == round(5 / 200, 4)
    assert body["complaint_rate"] == round(2 / 200, 4)


def test_overview_is_zero_safe_with_no_data(client, db, admin_user):
    res = client.get("/api/v1/admin/overview", headers=_staff_headers(admin_user))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {
        "factories": 0,
        "active_campaigns": 0,
        "pending_approvals": 0,
        "total_sent": 0,
        "bounce_rate": 0.0,
        "complaint_rate": 0.0,
    }

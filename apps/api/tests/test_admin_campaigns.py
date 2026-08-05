"""GET /admin/campaigns — cross-tenant campaign oversight for the staff console."""

from __future__ import annotations

from app.models import AuditLog, CampaignStatus, Factory
from app.security import create_access_token
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email, utcnow


def _staff_headers(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def _second_factory(db) -> Factory:
    f = Factory(
        name_ar="مصنع ثاني",
        name_en="Second Factory",
        sector="food",
        city="Riyadh",
        contact_person="Owner Two",
        contact_email="owner@secondfactory-export.com",
        postal_address="Riyadh, Saudi Arabia",
        sending_domain="secondfactory-export.com",
        spf_ok=True,
        dkim_ok=True,
        dmarc_ok=True,
        warmup_started_at=utcnow(),
        warmup_day=14,
    )
    db.add(f)
    db.commit()
    return f


def test_factory_user_cannot_list_campaigns(client, auth_headers):
    res = client.get("/api/v1/admin/campaigns", headers=auth_headers)
    assert res.status_code == 403, res.text


def test_staff_list_campaigns_across_tenants(client, db, factory, product, admin_user):
    # A campaign in each of two factories — staff must see both, each tagged
    # with its owning factory's names.
    c1 = make_campaign(db, factory, product)
    other = _second_factory(db)
    c2 = make_campaign(db, other, product, market_iso2="AE")
    c2.status = CampaignStatus.active
    db.commit()

    # Two draft (approval-pending) emails on c1, none on c2.
    b1, ct1 = make_buyer_with_contact(db, market_iso2="IN", email="a@buyer.example.in")
    b2, ct2 = make_buyer_with_contact(db, market_iso2="AE", email="b@buyer.example.ae")
    make_draft_email(db, c1, b1, ct1)
    make_draft_email(db, c1, b2, ct2)

    res = client.get("/api/v1/admin/campaigns", headers=_staff_headers(admin_user))
    assert res.status_code == 200, res.text
    rows = {r["id"]: r for r in res.json()}
    assert set(rows) == {str(c1.id), str(c2.id)}
    r1 = rows[str(c1.id)]
    assert r1["factory_name_en"] == "Test Factory"
    assert r1["factory_name_ar"] == "مصنع اختبار"
    assert r1["status"] == "draft"
    assert r1["pending_approvals"] == 2
    r2 = rows[str(c2.id)]
    assert r2["factory_name_en"] == "Second Factory"
    assert r2["status"] == "active"
    assert r2["pending_approvals"] == 0


def test_status_and_factory_filters(client, db, factory, product, admin_user):
    draft = make_campaign(db, factory, product)
    active = make_campaign(db, factory, product, market_iso2="AE")
    active.status = CampaignStatus.active
    db.commit()

    res = client.get("/api/v1/admin/campaigns?status=active", headers=_staff_headers(admin_user))
    assert res.status_code == 200, res.text
    assert [r["id"] for r in res.json()] == [str(active.id)]

    other = _second_factory(db)
    res = client.get(
        f"/api/v1/admin/campaigns?factory_id={other.id}", headers=_staff_headers(admin_user)
    )
    assert res.status_code == 200, res.text
    assert res.json() == []

    res = client.get(
        f"/api/v1/admin/campaigns?factory_id={factory.id}", headers=_staff_headers(admin_user)
    )
    assert {r["id"] for r in res.json()} == {str(draft.id), str(active.id)}


def test_pause_and_resume_are_audited(client, db, factory, product, admin_user):
    campaign = make_campaign(db, factory, product)
    campaign.status = CampaignStatus.active
    db.commit()

    res = client.post(
        f"/api/v1/admin/campaigns/{campaign.id}/pause?reason=complaints",
        headers=_staff_headers(admin_user),
    )
    assert res.status_code == 200, res.text
    db.expire_all()
    assert campaign.status == CampaignStatus.paused
    assert campaign.paused_reason == "complaints"

    res = client.post(
        f"/api/v1/admin/campaigns/{campaign.id}/resume",
        headers=_staff_headers(admin_user),
    )
    assert res.status_code == 200, res.text
    db.expire_all()
    assert campaign.status == CampaignStatus.active
    assert campaign.paused_reason is None

    actions = [
        a.action for a in db.query(AuditLog).filter(AuditLog.entity_id == str(campaign.id)).all()
    ]
    assert "campaign.paused_by_staff" in actions
    assert "campaign.resumed_by_staff" in actions

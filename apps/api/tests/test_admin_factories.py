"""B5 — factory pause/resume, staff DNS-verify audit, and audit pagination."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog
from app.security import create_access_token


def _headers(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def test_pause_and_resume_factory(client, db, admin_user, factory):
    h = _headers(admin_user)
    assert factory.sends_paused is False

    paused = client.post(
        f"/api/v1/admin/factories/{factory.id}/pause?reason=high+bounce", headers=h
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["sends_paused"] is True

    resumed = client.post(f"/api/v1/admin/factories/{factory.id}/resume", headers=h)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["sends_paused"] is False

    rows = db.scalars(select(AuditLog).where(AuditLog.entity_type == "factory")).all()
    actions = {r.action for r in rows}
    assert {"factory.paused", "factory.resumed"} <= actions


def test_mark_dns_verified_is_audited(client, db, admin_user, factory):
    factory.spf_ok = factory.dkim_ok = factory.dmarc_ok = False
    db.commit()
    res = client.post(
        f"/api/v1/admin/factories/{factory.id}/deliverability/verify", headers=_headers(admin_user)
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["spf_ok"] and body["dkim_ok"] and body["dmarc_ok"]
    rows = db.scalars(
        select(AuditLog).where(AuditLog.action == "factory.dns_verified_by_staff")
    ).all()
    assert len(rows) == 1


def test_audit_pagination_with_offset(client, db, admin_user, factory):
    h = _headers(admin_user)
    # Generate several audit rows.
    for _ in range(3):
        client.post(f"/api/v1/admin/factories/{factory.id}/pause?reason=x", headers=h)
        client.post(f"/api/v1/admin/factories/{factory.id}/resume", headers=h)

    page1 = client.get("/api/v1/admin/audit?limit=2&offset=0", headers=h)
    page2 = client.get("/api/v1/admin/audit?limit=2&offset=2", headers=h)
    assert page1.status_code == 200 and page2.status_code == 200
    ids1 = {r["id"] for r in page1.json()}
    ids2 = {r["id"] for r in page2.json()}
    assert len(ids1) == 2
    assert ids1.isdisjoint(ids2)  # offset advanced to a distinct page

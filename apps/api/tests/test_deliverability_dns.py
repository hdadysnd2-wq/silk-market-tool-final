"""A5 — DNS authentication is server-verified, never tenant-attested.

Tenants can no longer flip spf_ok/dkim_ok/dmarc_ok via PUT; the only path that
sets them is the server-side check, which resolves the domain's TXT records.
"""

from __future__ import annotations

from app.services import dns_check


def test_tenant_cannot_self_attest_dns(client, auth_headers, db, factory):
    factory.spf_ok = False
    factory.dkim_ok = False
    factory.dmarc_ok = False
    db.commit()

    # A tenant tries to assert authentication (and legitimately update the domain).
    res = client.put(
        "/api/v1/factory/deliverability",
        headers=auth_headers,
        json={"spf_ok": True, "dkim_ok": True, "dmarc_ok": True, "sending_domain": "acme.test"},
    )
    assert res.status_code == 200, res.text

    db.refresh(factory)
    # The self-attested flags are ignored…
    assert factory.spf_ok is False
    assert factory.dkim_ok is False
    assert factory.dmarc_ok is False
    # …while the non-privileged field still updates.
    assert factory.sending_domain == "acme.test"


def test_dns_check_sets_flags_from_resolved_records(client, auth_headers, db, factory, monkeypatch):
    factory.sending_domain = "acme.test"
    factory.spf_ok = False
    factory.dkim_ok = False
    factory.dmarc_ok = False
    db.commit()

    def fake_resolve(name: str) -> list[str]:
        if name == "acme.test":
            return ["v=spf1 include:_spf.google.com ~all"]
        if name == "_dmarc.acme.test":
            return ["v=DMARC1; p=reject; rua=mailto:dmarc@acme.test"]
        if name == "google._domainkey.acme.test":
            return ["v=DKIM1; k=rsa; p=MIGfMA0GCS..."]
        return []

    monkeypatch.setattr(dns_check, "_resolve_txt", fake_resolve)

    res = client.post("/api/v1/factory/deliverability/check", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["spf_ok"] is True
    assert body["dkim_ok"] is True
    assert body["dmarc_ok"] is True

    db.refresh(factory)
    assert factory.spf_ok is True
    assert factory.dkim_ok is True
    assert factory.dmarc_ok is True


def test_dns_check_reports_missing_records(client, auth_headers, db, factory, monkeypatch):
    factory.sending_domain = "bare.test"
    factory.spf_ok = True  # a previously-true flag must be corrected to false
    db.commit()

    monkeypatch.setattr(dns_check, "_resolve_txt", lambda name: [])

    res = client.post("/api/v1/factory/deliverability/check", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["spf_ok"] is False

    db.refresh(factory)
    assert factory.spf_ok is False


def test_dns_check_requires_a_sending_domain(client, auth_headers, db, factory):
    factory.sending_domain = None
    db.commit()

    res = client.post("/api/v1/factory/deliverability/check", headers=auth_headers)
    assert res.status_code == 400, res.text


def test_dns_check_writes_an_audit_row(client, auth_headers, db, factory, monkeypatch):
    from sqlalchemy import select

    from app.models import AuditLog

    factory.sending_domain = "acme.test"
    db.commit()
    monkeypatch.setattr(dns_check, "_resolve_txt", lambda name: [])

    client.post("/api/v1/factory/deliverability/check", headers=auth_headers)

    rows = db.scalars(select(AuditLog).where(AuditLog.action == "factory.dns_checked")).all()
    assert len(rows) == 1
    assert rows[0].payload["domain"] == "acme.test"


def test_check_deliverability_service_matches_records():
    def resolver(name: str) -> list[str]:
        return {
            "acme.test": ["v=spf1 ~all"],
            "_dmarc.acme.test": ["v=DMARC1; p=none"],
            "selector1._domainkey.acme.test": ["v=DKIM1; p=abc"],
        }.get(name, [])

    result = dns_check.check_deliverability(
        "acme.test", dkim_selectors=("default", "selector1"), resolver=resolver
    )
    assert result.spf_ok and result.dmarc_ok and result.dkim_ok
    assert "selector1" in result.notes["dkim"]

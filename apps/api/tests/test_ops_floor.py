"""Regression locks for the ops floor (Wave 2 item 1).

/health must exercise the real dependencies (DB, Redis, storage) and degrade to
503 when any is down — a static 200 hides a dead database from the platform
healthcheck. /metrics must expose request counters. sentry-sdk must live in the
main dependency group (the prod image installs with --no-dev, so a dev-only
declaration means no error reporting in production while the DSN "is set").
A stuck-product sweep must terminalize rows stranded by a lost worker.
"""

from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path

from app.models import Product, utcnow
from app.workers import tasks


def test_health_all_checks_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "redis": "ok", "storage": "ok"}


def test_health_degrades_to_503_when_a_dependency_is_down(client, monkeypatch):
    from app import observability

    monkeypatch.setattr(observability, "check_redis", lambda settings=None: "ConnectionError: down")
    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert "ConnectionError" in body["checks"]["redis"]
    assert body["checks"]["database"] == "ok"


def test_metrics_endpoint_exposes_request_counter(client):
    client.get("/health")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "silk_http_requests_total" in resp.text
    # Counted by route template, not raw path — bounded label cardinality.
    assert 'path="/health"' in resp.text


def test_sentry_sdk_is_a_prod_dependency():
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    main_deps = " ".join(pyproject["project"]["dependencies"])
    assert "sentry-sdk" in main_deps, "sentry-sdk must ship in the --no-dev prod image"
    assert "prometheus-client" in main_deps
    dev_deps = " ".join(pyproject["project"].get("optional-dependencies", {}).get("dev", []))
    assert "sentry-sdk" not in dev_deps, "one canonical declaration, in the main group"


def test_reconcile_stuck_products_terminalizes_stale_pending_only(db, factory):
    stale = Product(factory_id=factory.id, name_ar="قديم", name_en="Stale", currency="USD")
    fresh = Product(factory_id=factory.id, name_ar="جديد", name_en="Fresh", currency="USD")
    stale.classification_status = "pending"
    fresh.classification_status = "pending"
    db.add_all([stale, fresh])
    db.commit()
    # Backdate updated_at past the staleness window via SQL so the ORM's
    # onupdate hook cannot overwrite the value we are testing against.
    db.execute(
        Product.__table__.update()
        .where(Product.id == stale.id)
        .values(updated_at=utcnow() - timedelta(hours=2))
    )
    db.commit()

    result = tasks.reconcile_stuck_products.apply().result
    assert result == {"failed": 1}

    db.expire_all()
    assert db.get(Product, stale.id).classification_status == "failed"
    assert "stalled in 'pending'" in db.get(Product, stale.id).failure_reason
    assert db.get(Product, fresh.id).classification_status == "pending"

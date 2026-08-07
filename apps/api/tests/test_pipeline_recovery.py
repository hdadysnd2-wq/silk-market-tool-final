"""Regression locks for pipeline error recovery (audit blocker #4).

Before this fix, the intake and world-funnel tasks had no error handling: a
transient LLM/DB fault (or any exception) stranded the product/analysis in a
non-terminal status forever while the UI polled every 2s. Now transient faults
retry with backoff, permanent faults persist a terminal ``failed`` + reason, a
beat sweep reconciles rows stranded by a lost worker, and a real HS6 can be
entered manually even when the classifier proposed nothing.
"""

from __future__ import annotations

import contextlib
from datetime import timedelta

import httpx

from app.models import Analysis, Product, utcnow
from app.workers import tasks
from tests.conftest import make_buyer_with_contact  # noqa: F401  (fixture graph)


def test_is_transient_classifies_faults():
    assert tasks._is_transient(httpx.ConnectError("boom")) is True
    assert tasks._is_transient(httpx.TimeoutException("slow")) is True
    resp = httpx.Response(503, request=httpx.Request("GET", "http://x"))
    assert tasks._is_transient(httpx.HTTPStatusError("5xx", request=resp.request, response=resp))
    resp4 = httpx.Response(400, request=httpx.Request("GET", "http://x"))
    assert (
        tasks._is_transient(httpx.HTTPStatusError("4xx", request=resp4.request, response=resp4))
        is False
    )
    assert tasks._is_transient(ValueError("logic bug")) is False


def test_permanent_intake_failure_marks_product_failed(db, factory, monkeypatch):
    product = Product(factory_id=factory.id, name_ar="تمر", name_en="Dates", currency="USD")
    db.add(product)
    db.commit()

    def _boom(*a, **k):
        raise ValueError("model exploded")  # permanent → no retry

    # Fail the HS classification step: unlike vision (best-effort, skippable),
    # a classifier fault is fatal to the intake and must reach a terminal state.
    monkeypatch.setattr("app.services.hs_classifier.classify_product", _boom)

    res = tasks.process_product_intake.apply(args=[str(product.id)], throw=False)
    assert res.state == "FAILURE"

    db.expire_all()
    refreshed = db.get(Product, product.id)
    assert refreshed.classification_status == "failed"
    assert "model exploded" in (refreshed.failure_reason or "")


def test_vision_failure_degrades_without_blocking_intake(db, factory, monkeypatch):
    """Vision is best-effort enrichment: an exploding LLM must not fail the intake."""
    product = Product(factory_id=factory.id, name_ar="تمر", name_en="Dates", currency="USD")
    db.add(product)
    db.commit()

    class _Boom:
        def complete_with_image(self, *a, **k):
            raise ValueError("model exploded")

    monkeypatch.setattr("app.providers.registry.get_llm_provider", lambda: _Boom(), raising=True)

    res = tasks.process_product_intake.apply(args=[str(product.id)], throw=False)
    assert res.state == "SUCCESS"

    db.expire_all()
    refreshed = db.get(Product, product.id)
    assert refreshed.classification_status == "classified"  # engine still proposed HS6
    assert refreshed.failure_reason is None


def test_handle_pipeline_failure_marks_analysis_failed_when_retries_exhausted(db, factory, product):
    analysis = Analysis(product_id=product.id, product_name="Dates", status="ranked")
    db.add(analysis)
    db.commit()

    class _Task:
        max_retries = tasks._MAX_RETRIES

        class request:  # noqa: N801
            retries = tasks._MAX_RETRIES

    with contextlib.suppress(ValueError):  # re-raised for Celery visibility
        tasks._handle_pipeline_failure(_Task(), str(analysis.id), "stage2_enrich", ValueError("x"))

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    assert refreshed.status == "failed"
    assert "stage2_enrich" in (refreshed.failure_reason or "")


def test_handle_pipeline_failure_retries_transient(db, factory, product):
    analysis = Analysis(product_id=product.id, product_name="Dates", status="ranked")
    db.add(analysis)
    db.commit()

    calls = {}

    class _Task:
        max_retries = tasks._MAX_RETRIES

        class request:  # noqa: N801
            retries = 0

        def retry(self, *, exc, countdown):
            calls["retried"] = countdown
            raise exc

    with contextlib.suppress(httpx.ConnectError):
        tasks._handle_pipeline_failure(
            _Task(), str(analysis.id), "stage2_enrich", httpx.ConnectError("blip")
        )
    assert "retried" in calls  # transient → retried, not marked failed
    db.expire_all()
    assert db.get(Analysis, analysis.id).status == "ranked"


def test_reconcile_marks_stale_analysis_failed(db, factory, product):
    fresh = Analysis(product_id=product.id, product_name="Dates", status="ranked")
    db.add(fresh)
    db.commit()
    # Backdate updated_at past the staleness window.
    db.query(Analysis).filter(Analysis.id == fresh.id).update(
        {Analysis.updated_at: utcnow() - timedelta(hours=2)}
    )
    db.commit()

    out = tasks.reconcile_stuck_analyses.apply(throw=False)
    assert out.result["failed"] >= 1

    db.expire_all()
    refreshed = db.get(Analysis, fresh.id)
    assert refreshed.status == "failed"
    assert "stalled" in (refreshed.failure_reason or "")


def test_reconcile_leaves_terminal_and_fresh_analyses(db, factory, product):
    done = Analysis(product_id=product.id, product_name="Dates", status="deepened")
    recent = Analysis(product_id=product.id, product_name="Dates", status="ranked")
    db.add_all([done, recent])
    db.commit()
    db.query(Analysis).filter(Analysis.id == done.id).update(
        {Analysis.updated_at: utcnow() - timedelta(hours=2)}
    )
    db.commit()

    tasks.reconcile_stuck_analyses.apply(throw=False)
    db.expire_all()
    assert db.get(Analysis, done.id).status == "deepened"  # terminal untouched
    assert db.get(Analysis, recent.id).status == "ranked"  # fresh untouched


def test_manual_hs_entry_accepts_valid_code_absent_from_catalogue(
    client, auth_headers, db, factory
):
    """The manual fallback: a real HS6 the classifier never proposed is accepted."""
    product = Product(
        factory_id=factory.id,
        name_ar="منتج",
        name_en="Obscure Product",
        currency="USD",
        classification_status="failed",
        failure_reason="no candidate above threshold",
    )
    db.add(product)
    db.commit()

    from app.models import HSCode

    # A valid HS6 not in the seed catalogue.
    code = "845140"
    assert db.get(HSCode, code) is None

    resp = client.put(
        f"/api/v1/products/{product.id}/hs-code", json={"hs_code": code}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hs_code"] == code
    assert body["hs_confirmed_by_user"] is True
    assert db.get(HSCode, code) is not None  # backfilled from the WCO reference


def test_manual_hs_entry_rejects_structurally_invalid_code(client, auth_headers, db, factory):
    product = Product(factory_id=factory.id, name_ar="منتج", name_en="X", currency="USD")
    db.add(product)
    db.commit()

    resp = client.put(
        f"/api/v1/products/{product.id}/hs-code", json={"hs_code": "0000"}, headers=auth_headers
    )
    assert resp.status_code == 400

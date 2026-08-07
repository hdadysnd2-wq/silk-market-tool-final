"""Regression locks for symptom B: long-running analyses ending in a bad error.

Wave 3 diagnosis: SoftTimeLimitExceeded was classified permanent (with an empty
persisted message); the stuck-row reaper window (30 min) was SHORTER than one
stage's retry worst-case (~41 min) while no stage bumped the analysis row
mid-run; and a stage finishing after the reaper terminalized the row silently
overwrote `failed`. Each mechanism is locked here.
"""

from __future__ import annotations

from billiard.exceptions import SoftTimeLimitExceeded

from app.config import get_settings
from app.models import Analysis, CountryRanking, utcnow
from app.services import heartbeat
from app.workers import tasks


def test_soft_time_limit_is_transient_with_a_readable_reason():
    exc = SoftTimeLimitExceeded()
    assert tasks._is_transient(exc) is True
    reason = tasks._describe_failure(exc)
    assert "time limit" in reason
    assert not reason.endswith(": ")  # the old truncated "SoftTimeLimitExceeded: "


def test_reaper_window_exceeds_one_stage_retry_worst_case():
    """Config-consistency lock: the reaper must never kill a run that is merely
    slow. Worst case = (retries+1) executions at the soft limit + backoff."""
    settings = get_settings()
    executions = tasks._MAX_RETRIES + 1
    backoff = sum(tasks._RETRY_BACKOFF * (2**n) for n in range(tasks._MAX_RETRIES))
    worst_case_s = executions * settings.task_soft_time_limit_seconds + backoff
    assert settings.analysis_stuck_minutes * 60 > worst_case_s


def test_heartbeat_bumps_updated_at_in_its_own_transaction(db, factory, product):
    analysis = Analysis(product_id=product.id, product_name="Dates", status="ranked")
    db.add(analysis)
    db.commit()
    db.query(Analysis).filter(Analysis.id == analysis.id).update(
        {Analysis.updated_at: utcnow().replace(year=2020)}
    )
    db.commit()

    heartbeat.beat(analysis.id)

    db.expire_all()
    assert db.get(Analysis, analysis.id).updated_at.year >= 2026


def test_stage3_completion_never_overwrites_a_reaped_failure(db, factory, product, monkeypatch):
    analysis = Analysis(product_id=product.id, product_name="Dates", status="enriched")
    db.add(analysis)
    db.flush()
    db.add(
        CountryRanking(
            analysis_id=analysis.id,
            importer_iso3="DEU",
            year=2022,
            import_usd=700.0,
            screen_score=0.8,
            rank=1,
            stage=2,
        )
    )
    db.commit()

    # The reaper terminalizes the row from another transaction mid-stage.
    def _reap_during_deepdive(db_, analysis_, hs6_, product_):
        from app.db import SessionLocal

        with SessionLocal() as other:
            other.query(Analysis).filter(Analysis.id == analysis.id).update(
                {Analysis.status: "failed", Analysis.failure_reason: "reaped"}
            )
            other.commit()

    monkeypatch.setattr("app.services.stage3.deepdive_shortlist", _reap_during_deepdive)

    tasks.run_stage3_deepdive.apply(args=[str(analysis.id), "392010"], throw=False)

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    # The late completion must NOT flip the terminal failure back to success.
    assert refreshed.status == "failed"
    assert refreshed.failure_reason == "reaped"

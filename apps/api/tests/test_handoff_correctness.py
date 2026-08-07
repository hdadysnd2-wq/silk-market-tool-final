"""Stage-handoff correctness locks (audit findings C1, C2, C3, C5).

These regression tests pin the four handoff faults between the world-funnel
stages: a redelivered Stage 1 duplicating its shortlist (C1), Stage 2 running
before Stage 1 committed a ranking (C2), a post-commit broker fault dropping
Stage 3 and flipping a committed status to 'failed' (C3), and Stage 1
overwriting the reaper's terminal 'failed' after a mid-run terminalization (C5).

Celery runs eager here (see conftest), so ``.apply()`` / ``.delay()`` execute the
task inline against the test database — the same session discipline production
uses.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Analysis, CountryRanking, WorldTrade
from app.workers import tasks

HS6 = "392010"  # matches the confirmed hs_code on the `product` fixture


def _seed_world(db, hs6=HS6):
    """Six live (non-demo) markets so ``run_world_ranking`` clears the coverage gate."""
    markets = [
        ("IND", 1000.0),
        ("DEU", 900.0),
        ("BRA", 800.0),
        ("EGY", 700.0),
        ("KEN", 600.0),
        ("VNM", 500.0),
    ]
    for iso3, usd in markets:
        db.add(
            WorldTrade(
                hs6=hs6,
                importer_iso3=iso3,
                year=2022,
                import_usd=usd,
                is_transit_hub=False,
                is_mirror=False,
                source="UN Comtrade",
            )
        )
    db.commit()


def _ranking_count(db, analysis_id) -> int:
    db.expire_all()
    return db.scalar(
        select(func.count())
        .select_from(CountryRanking)
        .where(CountryRanking.analysis_id == analysis_id)
    )


# -- C1: a redelivered Stage 1 must REPLACE, not duplicate, the shortlist -------


def test_world_ranking_is_idempotent_on_redelivery(db, factory, product):
    """C1 — task_acks_late + task_reject_on_worker_lost can redeliver Stage 1 after
    the commit. The second run must delete-first and re-insert, leaving the
    CountryRanking count stable (no full duplicate set feeding Stage 2 / the
    executive report / GET)."""
    _seed_world(db)
    analysis = Analysis(product_id=product.id, product_name="Stretch Film", status="pending")
    db.add(analysis)
    db.commit()

    tasks.run_world_ranking.apply(args=[str(analysis.id), HS6], throw=False)
    first = _ranking_count(db, analysis.id)
    assert first == 5  # 6 seeded → top-20% shortlist quota floors at 5

    # Simulate the redelivery: run the exact same task again for the same analysis.
    tasks.run_world_ranking.apply(args=[str(analysis.id), HS6], throw=False)
    second = _ranking_count(db, analysis.id)

    assert second == first  # NOT doubled — the redelivery replaced the shortlist
    # 6 covered markets → the top-20% shortlist quota floors at SHORTLIST_MIN=5
    # (J1 transparent-screening change); the idempotency property is `second ==
    # first` above — this pins the deterministic kept count.
    assert second == 5


def test_rank_and_persist_is_idempotent(db, factory, product):
    """C1 (service layer) — calling ``rank_and_persist`` twice in one transaction
    replaces rather than appends, so the shortlist never carries duplicates."""
    from app.services.ranking import rank_and_persist

    _seed_world(db)
    analysis = Analysis(product_id=product.id, product_name="Stretch Film", status="classified")
    db.add(analysis)
    db.flush()

    rank_and_persist(db, analysis, HS6)
    rank_and_persist(db, analysis, HS6)
    db.commit()

    # Replace-not-append is the point; 6 covered → 5 kept by the shortlist quota.
    assert _ranking_count(db, analysis.id) == 5


# -- C2: Stage 2 must not run before Stage 1 has committed a ranking ------------


def test_enrich_on_pending_analysis_returns_409(client, db, product, auth_headers):
    """C2 (endpoint) — POST /enrich on a never-ranked analysis is a 409, even though
    the HS code is confirmed: enriching a 'pending' run would produce an 'enriched'
    analysis with zero rankings."""
    analysis = Analysis(product_id=product.id, product_name="Stretch Film", status="pending")
    db.add(analysis)
    db.commit()

    res = client.post(f"/api/v1/analyses/{analysis.id}/enrich", headers=auth_headers)
    assert res.status_code == 409, res.text


def test_stage2_task_does_not_enrich_a_pending_analysis(db, factory, product, monkeypatch):
    """C2 (task backstop) — even if the task is enqueued directly on a 'pending'
    analysis (bypassing the API gate), the transition must NOT promote it to
    'enriched'. ``enrich_shortlist`` is a no-op and the auto-chained Stage 3 is
    stubbed so the test isolates Stage 2's own status transition."""
    analysis = Analysis(product_id=product.id, product_name="Stretch Film", status="pending")
    db.add(analysis)
    db.commit()

    monkeypatch.setattr("app.services.stage2.enrich_shortlist", lambda *a, **k: [])
    monkeypatch.setattr(tasks.run_stage3_deepdive, "delay", lambda *a, **k: None)

    tasks.run_stage2_enrich.apply(args=[str(analysis.id), HS6], throw=False)

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    assert refreshed.status == "pending"  # never promoted — no zero-ranking 'enriched' run
    assert refreshed.status != "enriched"


# -- C3: a post-commit broker fault must not flip 'enriched' → 'failed' ---------


def test_stage2_broker_fault_after_commit_keeps_enriched(db, factory, product, monkeypatch):
    """C3 — the Stage-3 enqueue lives OUTSIDE the try, after the Stage-2 commit. A
    broker OperationalError on that enqueue (which ``_is_transient`` does NOT match)
    must not be caught by the stage's except and overwrite the just-committed
    'enriched' status with 'failed'."""
    from kombu.exceptions import OperationalError as BrokerError

    analysis = Analysis(product_id=product.id, product_name="Stretch Film", status="ranked")
    db.add(analysis)
    db.commit()

    # Isolate the enqueue-after-commit path: real enrichment is not what's under test.
    monkeypatch.setattr("app.services.stage2.enrich_shortlist", lambda *a, **k: [])

    def _broker_down(*a, **k):
        raise BrokerError("broker unavailable")

    monkeypatch.setattr(tasks.run_stage3_deepdive, "delay", _broker_down)

    # throw=False so the eager result captures the enqueue error instead of raising.
    tasks.run_stage2_enrich.apply(args=[str(analysis.id), HS6], throw=False)

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    assert refreshed.status == "enriched"  # the committed status survives the broker fault
    assert refreshed.failure_reason is None


# -- C5: Stage 1 must not overwrite the reaper's terminal 'failed' --------------


def test_world_ranking_completion_never_overwrites_a_reaped_failure(
    db, factory, product, monkeypatch
):
    """C5 — mirrors test_symptom_b_hardening's Stage-3 lock for Stage 1. The reaper
    terminalizes the row mid-run (its own transaction); Stage 1 finishing must
    re-read and skip the 'ranked' transition, leaving the 'failed' intact."""
    _seed_world(db)
    analysis = Analysis(product_id=product.id, product_name="Stretch Film", status="pending")
    db.add(analysis)
    db.commit()

    def _reap_during_ranking(db_, analysis_, hs6_, top_n=20):
        from app.db import SessionLocal

        with SessionLocal() as other:
            other.query(Analysis).filter(Analysis.id == analysis.id).update(
                {Analysis.status: "failed", Analysis.failure_reason: "reaped"}
            )
            other.commit()
        return []

    monkeypatch.setattr("app.services.ranking.rank_and_persist", _reap_during_ranking)

    aid = analysis.id
    tasks.run_world_ranking.apply(args=[str(aid), HS6], throw=False)

    # Read back through a fresh session — the heartbeat + reap mutated the row from
    # other transactions, so the fixture session's stale persistent object cannot
    # be relied on for the terminal read.
    from app.db import SessionLocal

    with SessionLocal() as check:
        refreshed = check.get(Analysis, aid)
        # The late completion must NOT flip the terminal failure back to 'ranked'.
        assert refreshed.status == "failed"
        assert refreshed.failure_reason == "reaped"

"""Regression locks for world_trade coverage handling (audit blocker #5).

The world funnel screened Stage 1 against a precomputed ``world_trade`` table
seeded with a 14-country x 6-HS demo. For any real HS6 without coverage the
screen returned a silent empty shortlist presented as a genuine world screen.
Now coverage is classified (none/demo/live), the funnel fails loudly on ``none``,
a fail-closed per-HS6 sync is requested, and a scheduled sweep refreshes codes
in active use.
"""

from __future__ import annotations

from datetime import timedelta

from app.models import Analysis, HSCode, Product, WorldTrade, utcnow
from app.services import world_funnel
from app.workers import tasks


def _row(hs6: str, iso3: str, source: str = "UN Comtrade") -> WorldTrade:
    return WorldTrade(
        hs6=hs6,
        importer_iso3=iso3,
        year=2024,
        import_usd=1_000_000,
        is_transit_hub=False,
        is_mirror=False,
        source=source,
    )


def test_coverage_state_none_demo_live(db):
    assert world_funnel.coverage_state(db, "999999") == "none"

    db.add(_row("111111", "DEU", source="UN Comtrade (demo seed)"))
    db.commit()
    assert world_funnel.coverage_state(db, "111111") == "demo"

    db.add(_row("222222", "DEU", source="UN Comtrade"))
    db.commit()
    assert world_funnel.coverage_state(db, "222222") == "live"


def test_world_ranking_holds_pending_and_chains_a_bound_sync(db, factory, product, monkeypatch):
    """With a LIVE trade-data source configured, missing coverage is a genuinely
    transient state: the analysis is NOT terminalized — it stays in its
    non-terminal status (the UI keeps polling it) while a sync BOUND to this
    analysis is enqueued, so the funnel completes with zero manual retries.
    The old behavior (fail + «please retry in a few minutes») was the recurring
    dead-end the owner kept hitting."""
    from app.config import get_settings

    analysis = Analysis(product_id=product.id, product_name="Dates", status="classified")
    db.add(analysis)
    db.commit()

    get_settings.cache_clear()
    monkeypatch.setenv("COMTRADE_OFFLINE", "0")
    monkeypatch.setenv("COMTRADE_API_KEY", "test-key")

    requested = {}
    monkeypatch.setattr(
        tasks.sync_world_trade, "delay", lambda hs6, **kw: requested.update({"hs6": hs6, **kw})
    )

    try:
        out = tasks.run_world_ranking.apply(args=[str(analysis.id), "999999"], throw=False).result
    finally:
        get_settings.cache_clear()
    assert out["coverage"] == "none"
    assert out["ranked"] == 0
    assert out["live_available"] is True
    assert out["sync_requested"] is True

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    # NOT failed: the run is still in flight; the chained sync completes it.
    assert refreshed.status == "classified"
    assert refreshed.failure_reason is None
    # The sync carries the analysis binding so it can re-dispatch the ranking.
    assert requested.get("hs6") == "999999"
    assert requested.get("analysis_id") == str(analysis.id)


def test_world_ranking_after_sync_without_coverage_is_terminal(db, factory, product, monkeypatch):
    """The chain is bounded to ONE cycle: a re-run flagged ``after_sync=True``
    that still finds no coverage terminalizes with a truthful reason — and no
    second sync is enqueued (no sync loops, no false retry promise)."""
    from app.config import get_settings

    analysis = Analysis(product_id=product.id, product_name="Dates", status="classified")
    db.add(analysis)
    db.commit()

    get_settings.cache_clear()
    monkeypatch.setenv("COMTRADE_OFFLINE", "0")
    monkeypatch.setenv("COMTRADE_API_KEY", "test-key")

    requested = []
    monkeypatch.setattr(
        tasks.sync_world_trade, "delay", lambda hs6, **kw: requested.append(hs6)
    )

    try:
        out = tasks.run_world_ranking.apply(
            args=[str(analysis.id), "999999"],
            kwargs={"after_sync": True},
            throw=False,
        ).result
    finally:
        get_settings.cache_clear()
    assert out["coverage"] == "none"
    assert out["live_available"] is True

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    assert refreshed.status == "failed"
    reason = refreshed.failure_reason or ""
    assert "999999" in reason
    assert "no world-trade rows" in reason.lower()
    assert "retry in a few minutes" not in reason.lower()
    assert requested == []  # bounded: never a second sync


def test_world_ranking_no_coverage_tells_the_truth_without_a_live_source(
    db, factory, product, monkeypatch
):
    """Regression: the failure message must not promise a retry that can never
    help. With no live trade-data source (no Comtrade key / offline), missing
    coverage is PERMANENT until an operator connects one — say so, and do NOT
    enqueue a fail-closed sync that would no-op. Never fabricate a screen (I1)."""
    from app.config import get_settings

    analysis = Analysis(product_id=product.id, product_name="Dates", status="classified")
    db.add(analysis)
    db.commit()

    get_settings.cache_clear()
    monkeypatch.setenv("COMTRADE_OFFLINE", "0")
    monkeypatch.setenv("COMTRADE_API_KEY", "")  # no live source

    requested = []
    monkeypatch.setattr(
        tasks.sync_world_trade, "delay", lambda hs6, **kw: requested.append(hs6)
    )

    try:
        out = tasks.run_world_ranking.apply(args=[str(analysis.id), "999999"], throw=False).result
    finally:
        get_settings.cache_clear()
    assert out["coverage"] == "none"
    assert out["live_available"] is False

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    assert refreshed.status == "failed"
    reason = refreshed.failure_reason or ""
    assert "999999" in reason
    assert "unavailable" in reason.lower()
    assert "retry in a few minutes" not in reason.lower()  # no false promise
    assert requested == []  # a fail-closed sync would only no-op — don't enqueue it


def test_sync_world_trade_fail_closed_offline(monkeypatch):
    """Offline / keyless never fabricates coverage — it declares unavailability."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("COMTRADE_OFFLINE", "1")
    monkeypatch.setenv("COMTRADE_API_KEY", "")
    try:
        out = tasks.sync_world_trade.apply(args=["392010"], throw=False).result
    finally:
        get_settings.cache_clear()
    assert out["synced"] is False
    assert "unavailable" in out["reason"]


def test_sync_world_trade_runs_when_live(monkeypatch):
    """The task imports the REAL ``etl.world_trade_sync`` module.

    The pre-remediation version of this test injected a fake ``etl`` module into
    ``sys.modules``, which passed even though the real package was absent from
    the production image (audit 2026-08-07 C1). Now the real module must import
    (its heavy pandas/comtradeapicall deps load lazily inside ``run()``, so the
    import itself is hermetic) and only the network-touching ``run`` is patched.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("COMTRADE_OFFLINE", "0")
    monkeypatch.setenv("COMTRADE_API_KEY", "test-key")

    # The repo root is on sys.path in production via the image's PYTHONPATH=/app
    # (locked below); mirror that here so the same real import resolves.
    import sys
    from pathlib import Path

    repo_root = str(Path(__file__).resolve().parents[3])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from etl import world_trade_sync as real_sync

    calls = {}

    def _run(code):
        calls["code"] = code
        return 42

    monkeypatch.setattr(real_sync, "run", _run)
    try:
        out = tasks.sync_world_trade.apply(args=["392010"], throw=False).result
    finally:
        get_settings.cache_clear()
    assert out == {"hs6": "392010", "synced": True, "rows": 42}
    assert calls["code"] == "392010"


def _etl_sync_module():
    """Import the real ``etl.world_trade_sync`` exactly as production resolves it."""
    import sys
    from pathlib import Path

    repo_root = str(Path(__file__).resolve().parents[3])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from etl import world_trade_sync as real_sync

    return real_sync


def test_sync_world_trade_chains_the_waiting_ranking(db, factory, product, monkeypatch):
    """The bound sync closes the loop end-to-end (eager): rows land → the SAME
    waiting analysis is re-ranked automatically (``after_sync=True``) — the
    user's single click completes with zero manual retries."""
    from app.config import get_settings
    from app.db import SessionLocal

    analysis = Analysis(product_id=product.id, product_name="Dates", status="classified")
    db.add(analysis)
    db.commit()

    get_settings.cache_clear()
    monkeypatch.setenv("COMTRADE_OFFLINE", "0")
    monkeypatch.setenv("COMTRADE_API_KEY", "test-key")
    real_sync = _etl_sync_module()

    def _run(code):
        # The real writer upserts world_trade rows; mirror that effect through
        # the app's own session factory so the chained eager re-rank sees them.
        s = SessionLocal()
        try:
            s.add(
                WorldTrade(
                    hs6=code,
                    importer_iso3="DEU",
                    year=2024,
                    import_usd=5_000_000,
                    is_transit_hub=False,
                    is_mirror=False,
                    source="UN Comtrade",
                )
            )
            s.commit()
        finally:
            s.close()
        return 1

    monkeypatch.setattr(real_sync, "run", _run)
    try:
        out = tasks.sync_world_trade.apply(
            args=["654321"], kwargs={"analysis_id": str(analysis.id)}, throw=False
        ).result
    finally:
        get_settings.cache_clear()
    assert out["synced"] is True and out["rows"] == 1
    assert out["reranked"] is True

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    assert refreshed.status == "ranked"  # the funnel completed without a human retry
    assert refreshed.failure_reason is None


def test_sync_world_trade_zero_rows_terminalizes_the_waiting_analysis(
    db, factory, product, monkeypatch
):
    """A sync that completes but writes nothing must not leave the bound analysis
    polling forever OR promise a retry: it terminalizes with a truthful reason
    and never re-dispatches the ranking (no loop on an unreported code)."""
    from app.config import get_settings

    analysis = Analysis(product_id=product.id, product_name="Dates", status="classified")
    db.add(analysis)
    db.commit()

    get_settings.cache_clear()
    monkeypatch.setenv("COMTRADE_OFFLINE", "0")
    monkeypatch.setenv("COMTRADE_API_KEY", "test-key")
    real_sync = _etl_sync_module()
    monkeypatch.setattr(real_sync, "run", lambda code: 0)

    reranked = []
    monkeypatch.setattr(
        tasks.run_world_ranking, "delay", lambda *a, **kw: reranked.append((a, kw))
    )
    try:
        out = tasks.sync_world_trade.apply(
            args=["654321"], kwargs={"analysis_id": str(analysis.id)}, throw=False
        ).result
    finally:
        get_settings.cache_clear()
    assert out["synced"] is True and out["rows"] == 0
    assert reranked == []

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    assert refreshed.status == "failed"
    reason = refreshed.failure_reason or ""
    assert "654321" in reason
    assert "no world-trade rows" in reason.lower()
    assert "retry in a few minutes" not in reason.lower()


def test_bound_sync_never_demotes_a_completed_analysis(db, factory, product, monkeypatch):
    """A racing/duplicate bound sync must never overwrite a finished run: the
    fail-closed path only terminalizes analyses still waiting (pending /
    classified) — a 'ranked' row keeps its result."""
    from app.config import get_settings

    analysis = Analysis(product_id=product.id, product_name="Dates", status="ranked")
    db.add(analysis)
    db.commit()

    get_settings.cache_clear()
    monkeypatch.setenv("COMTRADE_OFFLINE", "1")  # fail-closed branch
    monkeypatch.setenv("COMTRADE_API_KEY", "")
    try:
        out = tasks.sync_world_trade.apply(
            args=["654321"], kwargs={"analysis_id": str(analysis.id)}, throw=False
        ).result
    finally:
        get_settings.cache_clear()
    assert out["synced"] is False

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    assert refreshed.status == "ranked"  # untouched
    assert refreshed.failure_reason is None


def test_etl_package_ships_in_production_image():
    """Lock C1: the Dockerfile must COPY etl/ and put /app on PYTHONPATH.

    Without both, ``sync_world_trade`` ImportErrors forever in production and
    the world screen permanently fails for every real HS6.
    """
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "COPY etl /app/etl" in dockerfile, "etl/ must ship in the production image (C1)"
    assert "etl/requirements.txt" in dockerfile, "etl deps must install in the image (C1)"
    assert 'PYTHONPATH="/app"' in dockerfile, "/app must be importable so `from etl import …` works"


def test_refresh_world_trade_requests_stale_and_missing(db, factory, product, monkeypatch):
    # product fixture is a confirmed HS 392010 with no world_trade rows → missing.
    requested = []
    monkeypatch.setattr(tasks.sync_world_trade, "delay", lambda hs6: requested.append(hs6))

    out = tasks.refresh_world_trade.apply(throw=False).result
    assert out["sync_requested"] >= 1
    assert "392010" in requested


def test_refresh_world_trade_skips_fresh_coverage(db, factory, product, monkeypatch):
    db.add(
        WorldTrade(
            hs6=product.hs_code,
            importer_iso3="DEU",
            year=2024,
            import_usd=1_000_000,
            is_transit_hub=False,
            is_mirror=False,
            source="UN Comtrade",
            fetched_at=utcnow() - timedelta(days=1),  # fresh
        )
    )
    db.commit()

    requested = []
    monkeypatch.setattr(tasks.sync_world_trade, "delay", lambda hs6: requested.append(hs6))

    tasks.refresh_world_trade.apply(throw=False)
    assert product.hs_code not in requested  # fresh coverage is not re-synced


def test_refresh_world_trade_caps_dispatches_per_sweep(db, factory, product, monkeypatch):
    """Security review 2026-08-08 (finding 2.1): auto-classified codes enter the
    sweep with zero human action (ADR-0009), and Comtrade syncs live outside
    SILK_PAID_DAILY_CAP — the per-sweep fan-out must stay bounded, with the
    skip declared (world_trade_refresh_capped), never silent."""
    monkeypatch.setattr(tasks, "WORLD_TRADE_SWEEP_LIMIT", 3)
    for i in range(6):
        code = f"08041{i}"
        db.add(HSCode(code=code, level=6, description_en=f"c{i}", description_ar=f"c{i}"))
        db.add(
            Product(
                factory_id=factory.id,
                name_ar=f"منتج {i}",
                name_en=f"P{i}",
                currency="USD",
                hs_code=code,
                hs_auto_classified=True,  # machine-committed, no human click
                classification_status="classified",
            )
        )
    db.commit()

    requested = []
    monkeypatch.setattr(tasks.sync_world_trade, "delay", lambda hs6: requested.append(hs6))

    out = tasks.refresh_world_trade.apply(throw=False).result
    assert out["sync_requested"] == 3  # capped, not the full backlog
    assert len(requested) == 3

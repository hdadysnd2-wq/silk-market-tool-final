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

from app.models import Analysis, WorldTrade, utcnow
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


def test_world_ranking_fails_loudly_on_no_coverage(db, factory, product, monkeypatch):
    analysis = Analysis(product_id=product.id, product_name="Dates", status="classified")
    db.add(analysis)
    db.commit()

    requested = {}
    monkeypatch.setattr(
        tasks.sync_world_trade, "delay", lambda hs6: requested.setdefault("hs6", hs6)
    )

    out = tasks.run_world_ranking.apply(args=[str(analysis.id), "999999"], throw=False).result
    assert out["coverage"] == "none"
    assert out["ranked"] == 0

    db.expire_all()
    refreshed = db.get(Analysis, analysis.id)
    assert refreshed.status == "failed"
    assert "999999" in (refreshed.failure_reason or "")
    assert requested.get("hs6") == "999999"  # a coverage sync was requested


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
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("COMTRADE_OFFLINE", "0")
    monkeypatch.setenv("COMTRADE_API_KEY", "test-key")

    calls = {}

    import sys
    import types

    fake_sync = types.ModuleType("etl.world_trade_sync")

    def _run(code):
        calls["code"] = code
        return 42

    fake_sync.run = _run
    fake_etl = types.ModuleType("etl")
    fake_etl.world_trade_sync = fake_sync
    monkeypatch.setitem(sys.modules, "etl", fake_etl)
    monkeypatch.setitem(sys.modules, "etl.world_trade_sync", fake_sync)
    try:
        out = tasks.sync_world_trade.apply(args=["392010"], throw=False).result
    finally:
        get_settings.cache_clear()
    assert out == {"hs6": "392010", "synced": True, "rows": 42}
    assert calls["code"] == "392010"


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

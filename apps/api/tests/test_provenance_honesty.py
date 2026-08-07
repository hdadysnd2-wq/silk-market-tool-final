"""Regression locks: brain-path provenance honesty (audit C6/C7/C8/C9).

The executive report is the client deliverable — a fabricated or mislabeled
number in it is the worst class of defect. These lock the audit fixes: mock
buyers and fixture Comtrade data are marked as such, the score model/scale is
declared, and the Saudi share carries the engine's percent-point unit.
"""

from __future__ import annotations

from app.models import CountryRanking, MarketSnapshot
from app.services import engine
from app.services.buyer_discovery import discover_buyers
from app.services.competitor_snapshot import build_snapshot
from app.services.report_view import (
    _executive_buyers,
    _executive_market_row,
    build_executive_result,
)
from app.services.stage2 import _components_for


def test_mock_customs_buyers_are_flagged_demo_in_the_report(db, factory, product, market):
    # Discovery runs the deterministic MockShipmentsProvider in the test env.
    with engine.deepen_scope(False):
        discover_buyers(db, product, "IN")
    db.commit()

    buyers = _executive_buyers(db, product, "IN")
    assert buyers, "discovery produced buyers"
    # Every sample-derived buyer must be marked demo, never presented as
    # observed customs data (audit C6). Customs-sourced rows additionally carry
    # the loud "SAMPLE — " name prefix (J4); maps-sourced long-tail rows come
    # from the maps mock ("mock" provider) without the prefix.
    assert all(b["is_demo"] for b in buyers)
    assert all("mock" in (b["provider"] or "") or "sample" in (b["provider"] or "") for b in buyers)
    customs_named = [b for b in buyers if "sample" in (b["provider"] or "")]
    assert customs_named, "customs sample buyers present"
    assert all(b["name"].startswith("SAMPLE — ") for b in customs_named)


def test_offline_comtrade_snapshot_is_labeled_fixture(db, market):
    # COMTRADE_OFFLINE is the test default → fixture data, which must not present
    # as genuine live UN Comtrade (audit C7).
    snapshot = build_snapshot(db, "392010", "IN")
    assert snapshot.source == "comtrade_fixture"
    for row in snapshot.top_exporters:
        assert row["source"] == "comtrade_fixture"
        assert row["confidence"] < 0.9  # lowered from the live 0.9


def test_executive_score_declares_its_model(db, factory, product):
    a = _mk_analysis(db, product)
    # Stage-2 scored row → engine model label.
    r2 = _mk_ranking(
        db,
        a,
        "DEU",
        rank=1,
        stage2_score=0.7,
        enrichment={"score_confidence": 0.75, "score_model": "silk_market_ranker"},
    )
    # Screen-only row → the stage-1 fallback label (different scale).
    r1 = _mk_ranking(db, a, "IND", rank=2, screen_score=1234.0)
    db.commit()

    row2 = _executive_market_row(db, product, r2)
    row1 = _executive_market_row(db, product, r1)
    assert row2["score_model"] == "silk_market_ranker"
    assert row1["score_model"] == "stage1_screen"


def test_saudi_share_stored_in_percent_points(db, factory, product):
    snap = MarketSnapshot(
        hs_code="392010",
        market_iso2="IN",
        total_import_usd=900.0,
        top_exporters=[
            {
                "exporter_iso2": "SA",
                "exporter_name": "Saudi Arabia",
                "share_pct": 30.0,
                "value_usd": 270.0,
            },
            {
                "exporter_iso2": "CN",
                "exporter_name": "China",
                "share_pct": 40.0,
                "value_usd": 360.0,
            },
        ],
        source="comtrade",
    )
    db.add(snap)
    db.commit()

    r = _mk_ranking(db, _mk_analysis(db, product), "IND", rank=1, import_usd=900.0)
    components = _components_for(db, "392010", r, ppp=None, ppp_source="worldbank")
    # Percent-points (30.0), not the 0..1 fraction that rendered 0.3% (audit C9).
    assert components["saudi_position"]["value"] == 30.0


def test_build_executive_result_zero_analyses_is_a_declared_gap(db, factory, product):
    result = build_executive_result(db, product)
    assert result["executive"]["markets"] == []  # I1 — absent, never fabricated


# -- helpers ---------------------------------------------------------------


def _mk_analysis(db, product):
    from app.models import Analysis

    a = Analysis(product_id=product.id, product_name=product.name_en, status="ranked")
    db.add(a)
    db.flush()
    return a


def _mk_ranking(
    db,
    analysis,
    iso3,
    *,
    rank,
    stage2_score=None,
    screen_score=0.5,
    import_usd=100.0,
    enrichment=None,
):
    r = CountryRanking(
        analysis_id=analysis.id,
        importer_iso3=iso3,
        year=2022,
        import_usd=import_usd,
        screen_score=screen_score,
        stage2_score=stage2_score,
        rank=rank,
        stage=2 if stage2_score is not None else 1,
        enrichment=enrichment,
    )
    db.add(r)
    db.flush()
    return r

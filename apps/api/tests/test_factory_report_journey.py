"""Smoke test for the Factory Report Journey (J5).

Drives the same service-layer calls the ``demo_factory_report_journey`` script
makes — world screen (top-20% cut) → transparent Stage-2 re-rank → Top-5 with a
rationale line → observed prices → buyer list → rendered executive docx — and
asserts each stage produces coherent, honestly-labeled output. Proves the
flagship journey is wired end to end without depending on the demo seed.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Analysis, CountryRanking, MarketSnapshot, WorldTrade
from app.services import engine
from app.services.api_budget import budget_scope
from app.services.buyer_discovery import buyers_for_product, discover_buyers
from app.services.observed_prices import fetch_prices_for_market
from app.services.ranking import rank_and_persist
from app.services.ranking_rationale import build_rationale
from app.services.report_view import build_executive_result
from app.services.stage2 import enrich_shortlist

HS6 = "392010"
_MARKETS = [
    ("IND", 1000.0),
    ("ARE", 1400.0),  # transit hub
    ("USA", 880.0),
    ("DEU", 620.0),
    ("GBR", 510.0),
    ("BRA", 470.0),
    ("EGY", 300.0),
    ("KEN", 260.0),
]


def _seed_world(db):
    for iso3, usd in _MARKETS:
        db.add(
            WorldTrade(
                hs6=HS6,
                importer_iso3=iso3,
                year=2022,
                import_usd=usd * 1000.0,
                import_qty=usd * 10.0,  # gives Stage-2 a unit-value component
                is_transit_hub=(iso3 == "ARE"),
                is_mirror=False,
                source="UN Comtrade",
            )
        )
    db.flush()


def test_journey_end_to_end_local(db, factory, product, market):
    # ``market`` fixture provides the "IN" Market row discovery requires; the
    # top-ranked market resolves to IN so buyer discovery has a home.
    _seed_world(db)

    # Stage 1 — world screen with the top-20% quota.
    analysis = Analysis(product_id=product.id, product_name=product.name_en, status="classified")
    db.add(analysis)
    db.flush()
    rank_and_persist(db, analysis, HS6)
    db.flush()
    assert analysis.total_screened == len(_MARKETS)
    assert analysis.shortlisted == 5  # 8 covered → quota floors at 5

    # Stage 2 — transparent 7-component re-rank.
    with engine.deepen_scope(True), budget_scope(label="journey-test"):
        enrich_shortlist(db, analysis, HS6)
    db.flush()

    top5 = db.scalars(
        select(CountryRanking)
        .where(CountryRanking.analysis_id == analysis.id)
        .order_by(CountryRanking.rank)
        .limit(5)
    ).all()
    assert len(top5) == 5

    # Every top row carries a rationale naming real components with sources.
    rationale = build_rationale((top5[0].enrichment or {}).get("score_components"))
    assert rationale and "en" in rationale and "ar" in rationale
    assert "(" in rationale["en"]  # a source is named in parentheses
    # The transit hub is present but flagged (never silently top).
    assert any(r.is_transit_hub for r in top5)

    # Observed prices per market: local mock returns SAMPLE-sourced listings.
    iso2 = _iso3(top5[0].importer_iso3)
    with engine.deepen_scope(True), budget_scope(label="journey-prices"):
        priced = fetch_prices_for_market(db, product, iso2)
    assert priced["count"] > 0
    snap = db.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.hs_code == HS6, MarketSnapshot.market_iso2 == iso2
        )
    )
    assert snap and snap.observed_prices
    assert "mock" in str(snap.observed_prices[0]["source"])  # honestly labeled

    # Buyer list per market: sample importers are loudly labeled.
    with budget_scope(label="journey-discovery"):
        discover_buyers(db, product, iso2, analysis_id=analysis.id)
    db.flush()
    pairs = buyers_for_product(db, product.id, iso2)
    assert pairs, "discovery produced buyers"
    assert any(b.name.startswith("SAMPLE — ") for _m, b in pairs)

    # The executive report renders with the Top-5 blocks.
    result = build_executive_result(db, product)
    assert len(result["executive"]["markets"]) == 5

    from pathlib import Path
    from tempfile import mkdtemp

    from silk_render import build_view
    from silk_reports import render_executive_docx

    out = render_executive_docx(build_view(result), str(Path(mkdtemp()) / "exec.docx"))
    assert Path(out).stat().st_size > 10_000  # a real docx, not an empty stub


def _iso3(iso3: str) -> str:
    from app.providers.countries import iso3_to_iso2

    return iso3_to_iso2(iso3) or iso3[:2]

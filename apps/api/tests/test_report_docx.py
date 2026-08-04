"""Full report as a Word document, derived from the engine's build_view (decision #7).

The ``.docx`` export goes through the ONE engine template
(``build_engine_result`` → ``silk_render.build_view`` → ``silk_reports.render_docx``):
it must carry a source line under every figure and the "limits of this report"
section, and never fabricate — a value the platform cannot source (demand-capacity,
the weighted verdict/score) is a declared gap, not a zero (I1).
"""

from __future__ import annotations

from app.models import MarketSnapshot, WorldTrade
from app.services.ranking import run_product_world_analysis
from app.services.report_view import build_engine_result


def _seed_funnel(db, product):
    """Seed world_trade and run the funnel so the product has a persisted analysis."""
    rows = [
        ("DEU", 700.0, False, False),  # genuine demand
        ("NLD", 1000.0, True, False),  # transit hub — highest raw volume
        ("IND", 500.0, False, True),  # mirror
    ]
    for iso3, usd, hub, mirror in rows:
        db.add(
            WorldTrade(
                hs6=product.hs_code,
                importer_iso3=iso3,
                year=2022,
                import_usd=usd,
                is_transit_hub=hub,
                is_mirror=mirror,
                source="UN Comtrade",
            )
        )
    db.commit()
    run_product_world_analysis(db, product)
    db.commit()


def _snapshot_with_saudi(db, hs_code):
    db.add(
        MarketSnapshot(
            hs_code=hs_code,
            market_iso2="DE",
            total_import_usd=900.0,
            trend_pct=5.0,
            top_exporters=[
                {
                    "exporter_iso2": "CN",
                    "exporter_name": "China",
                    "value_usd": 400.0,
                    "share_pct": 40.0,
                },
                {
                    "exporter_iso2": "SA",
                    "exporter_name": "Saudi Arabia",
                    "value_usd": 120.0,
                    "share_pct": 12.0,
                },
            ],
            yearly_values=[{"year": 2022, "value_usd": 900.0}],
            source="comtrade",
            provider_name="comtrade",
        )
    )
    db.commit()


def test_build_engine_result_sources_figures_and_declares_gaps(db, factory, product):
    _seed_funnel(db, product)
    _snapshot_with_saudi(db, product.hs_code)

    result = build_engine_result(db, product)
    assert result["hs_code"] == product.hs_code
    assert result["markets"], "the funnel top-5 feed the report markets"

    de = next(m for m in result["markets"] if m["iso3"] == "DEU")
    ms = de["components"]["market_size"]
    assert ms["value"] == 900.0 and ms["confidence"] == 0.9  # sourced from the snapshot
    # I1 — demand_capacity has no platform source → declared gap, never a zero.
    dc = de["components"]["demand_capacity"]
    assert dc["value"] is None and dc["confidence"] == 0.0
    # Saudi supplier share extracted from the snapshot's exporters.
    assert de["components"]["saudi_position"]["value"] == 0.12

    # I9 — a transit hub keeps its visible tag on the figure's provenance.
    nld = next(m for m in result["markets"] if m["iso3"] == "NLD")
    assert "transit" in nld["components"]["market_size"]["note"].lower()


def test_view_keeps_source_lines_and_limits(db, factory, product):
    from silk_render import build_view

    _seed_funnel(db, product)
    view = build_view(build_engine_result(db, product))

    # decision #7 — the "limits of this report" section is never compressed away.
    assert view.get("limits") is not None
    # Every figure carries a source line (components_detail under each market).
    top = (view.get("markets") or [{}])[0]
    assert top.get("components_detail")


def test_report_docx_endpoint_returns_a_word_file(client, auth_headers, db, factory, product):
    _seed_funnel(db, product)

    res = client.get(f"/api/v1/products/{product.id}/report.docx", headers=auth_headers)

    assert res.status_code == 200
    assert "openxmlformats" in res.headers["content-type"]
    assert res.content[:2] == b"PK"  # a .docx is a zip archive
    assert len(res.content) > 2000  # a real document, not an empty stub

"""The funnel brief carries a source line under every figure + a limits section.

Decision #7 non-negotiables: never compress away the source line under every
number or the "limits of this report" section. A missing figure is a declared
gap (I1), never a fabricated number.
"""

from __future__ import annotations

from app.models import WorldTrade

HS6 = "392010"  # the confirmed hs_code on the `product` fixture


def _seed_world(db, hs6=HS6):
    rows = [
        ("NLD", 1000.0, True, False),
        ("DEU", 700.0, False, False),
        ("IND", 500.0, False, True),
        ("SGP", 400.0, True, False),
        ("XXX", None, False, False),
    ]
    for iso3, usd, hub, mirror in rows:
        db.add(
            WorldTrade(
                hs6=hs6,
                importer_iso3=iso3,
                year=2022,
                import_usd=usd,
                is_transit_hub=hub,
                is_mirror=mirror,
                source="UN Comtrade",
            )
        )
    db.commit()


def _run_analysis(client, product, auth_headers) -> str:
    return client.post(f"/api/v1/products/{product.id}/analysis", headers=auth_headers).json()["id"]


def test_brief_has_sourced_numbers_and_limits(client, db, product, auth_headers):
    _seed_world(db)
    aid = _run_analysis(client, product, auth_headers)

    resp = client.get(f"/api/v1/analyses/{aid}/brief", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    brief = resp.json()

    assert brief["hs_code"] == HS6
    assert "DEU" in brief["decision"]  # genuine market tops the decision line

    # Decision #7 — a source line under EVERY decisive number, never omitted.
    assert len(brief["decisive_numbers"]) == 3
    assert all(fig["source"] for fig in brief["decisive_numbers"])
    assert brief["decisive_numbers"][0]["year"] == 2022  # year travels with the figure

    # The competitive-position lines surface the transit-hub demotion.
    assert any("transit hub" in line for line in brief["competitive_position"])

    # The "limits of this report" section is present and declares the gaps (I1).
    assert brief["limits"]
    assert any("no reported import data" in limit for limit in brief["limits"])  # XXX
    assert any("Stage-1" in limit for limit in brief["limits"])


def test_analysis_persists_and_exposes_total_screened(client, db, product, auth_headers):
    _seed_world(db)  # 5 markets screened worldwide
    run = client.post(f"/api/v1/products/{product.id}/analysis", headers=auth_headers).json()
    # The true world count is persisted and returned, not the shortlist length.
    assert run["total_screened"] == 5


def test_brief_shows_full_funnel_transparency(client, db, product, auth_headers):
    _seed_world(db)  # 5 screened → 5 shortlisted → top 5
    aid = _run_analysis(client, product, auth_headers)
    brief = client.get(f"/api/v1/analyses/{aid}/brief", headers=auth_headers).json()
    # "screened N → shortlisted M → top K" with the real world count (decision #7).
    assert any(
        "Screened 5 markets worldwide" in line and "shortlisted" in line and "top" in line
        for line in brief["competitive_position"]
    ), brief["competitive_position"]


def test_brief_declares_gap_when_no_world_data(client, db, product, auth_headers):
    # No world_trade seeded → the funnel has nothing to rank.
    aid = _run_analysis(client, product, auth_headers)

    brief = client.get(f"/api/v1/analyses/{aid}/brief", headers=auth_headers).json()
    assert "No world-trade data" in brief["decision"]
    assert brief["decisive_numbers"] == []
    # Even with no data, the limits section is never dropped (decision #7).
    assert brief["limits"]

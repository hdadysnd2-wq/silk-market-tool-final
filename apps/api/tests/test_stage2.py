"""Funnel Stage 2 — budgeted enrichment of the shortlist → re-ranked top 5.

Stage 2 enriches the persisted Stage-1 shortlist with applied-tariff + PPP signals
under the per-analysis API budget (decision #5) and re-ranks to the top 5. Every
signal is real or a declared gap (I1): a market whose enrichment fails keeps its
Stage-1 score. The budget caps the pass — exhausting it stops enrichment early
rather than running the key dry.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Analysis, CountryRanking, WorldTrade
from app.services import api_budget
from app.services.stage2 import enrich_shortlist

HS6 = "392010"  # the confirmed hs_code on the `product` fixture


def _seed_world(db, hs6=HS6):
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


def _run_stage1(client, product, auth_headers) -> str:
    # Async world funnel: POST is accepted (202); under eager mode the ranking task
    # ran in-process, so the analysis id already resolves a ranked Stage-1 run.
    resp = client.post(f"/api/v1/products/{product.id}/analysis", headers=auth_headers)
    assert resp.status_code == 202, resp.text
    return resp.json()["analysis"]["id"]


def test_stage2_uses_the_engine_weighted_model():
    """The old product-local tariff-drag heuristic is gone (Wave 3 item 2):
    scoring delegates to the engine's audited component model via the seam."""
    from app.services import engine

    scored = engine.score_market_components(
        [
            {
                "iso3": "DEU",
                "components": {
                    "market_size": {"value": 900.0, "source": "world_trade"},
                    "demand_capacity": {"value": 60_000.0, "source": "worldbank"},
                },
            },
            {
                "iso3": "IND",
                "components": {"market_size": {"value": 500.0, "source": "world_trade"}},
            },
        ]
    )
    by = {s["iso3"]: s for s in scored}
    # Scores are the engine's 0..1 weighted totals; more present components →
    # higher row confidence. Nothing is fabricated for the missing signals.
    assert 0.0 <= by["IND"]["total_score"] <= by["DEU"]["total_score"] <= 1.0
    assert by["DEU"]["confidence"] > by["IND"]["confidence"]


def test_enrich_reranks_shortlist_and_persists_stage2(client, db, product, auth_headers):
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)

    # Async Stage 2: POST is accepted (202); under eager mode the enrich task ran
    # in-process, so GET carries the re-ranked, enriched shortlist.
    res = client.post(f"/api/v1/analyses/{aid}/enrich", headers=auth_headers)
    assert res.status_code == 202, res.text
    assert res.json()["task_id"]

    out = client.get(f"/api/v1/analyses/{aid}", headers=auth_headers).json()
    # Stage 2 auto-chains the free Stage-3 deep-dive, so the terminal is `deepened`.
    assert out["status"] in ("enriched", "deepened")

    rankings = out["rankings"]
    assert rankings, "shortlist present"
    # Every enriched row carries a Stage-2 score + signals; the top-5 finalists are
    # then promoted to stage 3 by the auto-chained deep-dive (stage 2 for the rest).
    for r in rankings:
        assert r["stage"] in (2, 3)
        assert r["stage2_score"] is not None
        assert r["enrichment"] is not None
        assert "applied_tariff_pct" in r["enrichment"]
    # Ranks are 1..N and ordered by the Stage-2 score (the re-ranking took effect).
    assert [r["rank"] for r in rankings] == list(range(1, len(rankings) + 1))
    scores = [r["stage2_score"] for r in rankings]
    assert scores == sorted(scores, reverse=True)


def test_enrich_brief_reflects_stage2(client, db, product, auth_headers):
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    res = client.post(f"/api/v1/analyses/{aid}/enrich", headers=auth_headers)
    assert res.status_code == 202, res.text

    brief = client.get(f"/api/v1/analyses/{aid}/brief", headers=auth_headers).json()
    assert any("Stage-2" in line for line in brief["competitive_position"])
    # The Stage-1-only caveat is gone; a Stage-2 caveat replaces it.
    assert not any(limit == _stage1_limit() for limit in brief["limits"])
    assert any("Stage-2 applied tariff" in limit for limit in brief["limits"])
    # A source line now carries the applied tariff.
    assert any("tariff" in fig["source"] for fig in brief["decisive_numbers"])


def _stage1_limit() -> str:
    from app.services.funnel_brief import _STAGE1_LIMIT

    return _STAGE1_LIMIT


def test_enrich_requires_confirmed_hs(client, db, product, auth_headers):
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    product.hs_confirmed_by_user = False
    db.commit()

    res = client.post(f"/api/v1/analyses/{aid}/enrich", headers=auth_headers)
    assert res.status_code == 409  # I2


def test_enrich_stops_at_the_budget(client, db, product, auth_headers):
    # A budget smaller than the shortlist enriches only what it can afford. The
    # unenriched rest still get an engine cohort score from the components they
    # DO hold (import volume) — with fewer components and therefore a lower
    # score confidence, never a fabricated signal (Wave 3 item 2 semantics).
    _seed_world(db)  # 6 markets
    aid = _run_stage1(client, product, auth_headers)
    analysis = db.get(Analysis, uuid.UUID(aid))

    with api_budget.budget_scope(limit=2):
        enrich_shortlist(db, analysis, HS6)

    rows = db.scalars(select(CountryRanking).where(CountryRanking.analysis_id == analysis.id)).all()
    enriched = [r for r in rows if r.stage == 2]
    assert len(enriched) == 2  # budget allowed exactly two enrichment calls
    unreached = [r for r in rows if r.stage == 1]
    assert unreached  # the rest were never promoted to stage 2
    for r in unreached:
        assert r.stage2_score is not None  # scored from persisted components
        conf = (r.enrichment or {}).get("score_confidence")
        assert conf is not None and conf < 1.0  # fewer components = lower confidence


# ── J1: the three new engine components come from REAL persisted data ────────


def test_unit_price_component_derived_from_world_trade_qty(client, db, product, auth_headers):
    # A world_trade row with a positive quantity yields the observed Comtrade
    # unit value (import_usd / import_qty) as the unit_price_level component.
    _seed_world(db)
    deu_row = db.scalar(
        select(WorldTrade).where(WorldTrade.hs6 == HS6, WorldTrade.importer_iso3 == "DEU")
    )
    deu_row.import_qty = 450.0
    db.commit()
    aid = _run_stage1(client, product, auth_headers)
    analysis = db.get(Analysis, uuid.UUID(aid))

    enrich_shortlist(db, analysis, HS6)
    rows = {
        r.importer_iso3: r
        for r in db.scalars(select(CountryRanking).where(CountryRanking.analysis_id == analysis.id))
    }
    deu = rows["DEU"].enrichment["score_components"]["unit_price_level"]
    assert deu["value"] == 900.0 / 450.0
    assert deu["source"] == "world_trade"
    assert deu["note"] == "Comtrade unit value USD/qty"
    # Rows without a quantity OMIT the component — a declared gap (I1), never a
    # fabricated unit value.
    assert "unit_price_level" not in rows["IND"].enrichment["score_components"]


def test_tariff_access_component_comes_from_the_enrichment_record(
    client, db, product, auth_headers
):
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    analysis = db.get(Analysis, uuid.UUID(aid))

    enrich_shortlist(db, analysis, HS6)
    rows = list(db.scalars(select(CountryRanking).where(CountryRanking.analysis_id == analysis.id)))
    enriched = [r for r in rows if (r.enrichment or {}).get("applied_tariff_pct") is not None]
    assert enriched, "the mock enrichment provider supplies a tariff"
    for r in enriched:
        comp = r.enrichment["score_components"]["tariff_access"]
        # The component's value IS the persisted enrichment tariff; its source is
        # the enrichment record's provider — no separate/parallel tariff source.
        assert comp["value"] == r.enrichment["applied_tariff_pct"]
        assert comp["source"] == r.enrichment["source"]
        assert comp["note"] == "applied import tariff for HS6"


def test_tariff_component_omitted_when_enrichment_is_gated(
    client, db, product, auth_headers, monkeypatch
):
    # Keyless prod: the Gated provider returns None → tariff_access is simply
    # omitted (a declared gap, I1), never fabricated.
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    analysis = db.get(Analysis, uuid.UUID(aid))

    import app.services.stage2 as stage2_mod
    from app.providers.market_enrichment.gated import GatedMarketEnrichmentProvider

    monkeypatch.setattr(
        stage2_mod, "get_market_enrichment_provider", lambda: GatedMarketEnrichmentProvider()
    )
    enrich_shortlist(db, analysis, HS6)
    rows = list(db.scalars(select(CountryRanking).where(CountryRanking.analysis_id == analysis.id)))
    for r in rows:
        assert "tariff_access" not in r.enrichment["score_components"]


def test_logistics_proximity_component_from_derived_distance_table(
    client, db, product, auth_headers
):
    from app.providers.countries_distance import DISTANCE_SOURCE, distance_from_jeddah_km

    # The static table covers the major importers the funnel screens.
    for iso3 in ("DEU", "IND", "CHN"):
        assert distance_from_jeddah_km(iso3) is not None

    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    analysis = db.get(Analysis, uuid.UUID(aid))
    enrich_shortlist(db, analysis, HS6)
    rows = {
        r.importer_iso3: r
        for r in db.scalars(select(CountryRanking).where(CountryRanking.analysis_id == analysis.id))
    }
    for iso3 in ("DEU", "IND"):
        comp = rows[iso3].enrichment["score_components"]["logistics_proximity"]
        assert comp["value"] == distance_from_jeddah_km(iso3)
        assert comp["source"] == DISTANCE_SOURCE


def test_top5_rows_carry_a_deterministic_rationale(client, db, product, auth_headers):
    # J1 transparency: after Stage 2, the API's top-5 rows each carry EN + AR
    # one-liners naming top components with their real values and sources.
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    res = client.post(f"/api/v1/analyses/{aid}/enrich", headers=auth_headers)
    assert res.status_code == 202, res.text

    out = client.get(f"/api/v1/analyses/{aid}", headers=auth_headers).json()
    top5 = out["rankings"][:5]
    assert top5
    for r in top5:
        assert r["rationale_en"] and r["rationale_ar"]
        # market_size (weight .30) is present on every seeded row, so it must be
        # one of the named top contributors — with its real source label.
        assert "market size" in r["rationale_en"]
        assert "world_trade" in r["rationale_en"]
        assert "حجم السوق" in r["rationale_ar"]
        # The components themselves are exposed for the breakdown UI.
        assert "score_components" in r["enrichment"]


def test_enrich_market_gap_keeps_stage1_score(client, db, product, auth_headers, monkeypatch):
    # I1 — a failed enrichment keeps the Stage-1 score and records the gap, never
    # a fabricated signal.
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    analysis = db.get(Analysis, uuid.UUID(aid))

    import app.services.stage2 as stage2_mod

    class _NullProvider:
        name = "null"

        def enrich_market(self, importer_iso3, hs6):
            return None

    monkeypatch.setattr(stage2_mod, "get_market_enrichment_provider", lambda: _NullProvider())

    enrich_shortlist(db, analysis, HS6)
    rows = db.scalars(select(CountryRanking).where(CountryRanking.analysis_id == analysis.id)).all()
    for r in rows:
        assert r.stage == 1  # never promoted to stage 2 on a gap
        # The engine cohort score is computed from the components the platform
        # actually holds (import volume only here — the enrichment gap means no
        # demand_capacity component was ever fed in, not a fabricated one).
        assert r.stage2_score is not None and 0.0 <= float(r.stage2_score) <= 1.0
        assert r.enrichment["note"] == "enrichment unavailable"
        assert "demand_capacity" not in r.enrichment["score_components"]
        assert r.enrichment["score_confidence"] < 1.0

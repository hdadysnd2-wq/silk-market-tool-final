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
from app.services.stage2 import enrich_shortlist, stage2_score

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


def test_stage2_score_applies_tariff_drag_and_ppp_lift():
    base = 100.0
    # No signals → unchanged.
    assert stage2_score(base, None, None) == 100.0
    # 20% tariff → ×0.8 (and no ppp).
    assert stage2_score(base, 0.20, None) == 80.0
    # PPP lifts within a bounded band; higher PPP never explodes the score.
    assert stage2_score(base, None, 0.0) == 85.0
    assert stage2_score(base, None, 65_000.0) == 115.0


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
    # A budget smaller than the shortlist enriches only what it can afford; the
    # rest keep their Stage-1 score (no fabricated signal).
    _seed_world(db)  # 6 markets
    aid = _run_stage1(client, product, auth_headers)
    analysis = db.get(Analysis, uuid.UUID(aid))

    with api_budget.budget_scope(limit=2):
        enrich_shortlist(db, analysis, HS6)

    rows = db.scalars(select(CountryRanking).where(CountryRanking.analysis_id == analysis.id)).all()
    enriched = [r for r in rows if r.stage == 2]
    assert len(enriched) == 2  # budget allowed exactly two enrichment calls
    assert any(r.stage == 1 and r.stage2_score is None for r in rows)  # rest untouched


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
        assert float(r.stage2_score) == float(r.screen_score)  # fell back, not fabricated
        assert r.enrichment["note"] == "enrichment unavailable"

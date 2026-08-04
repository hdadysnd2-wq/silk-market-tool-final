"""Funnel Stage 3 — FREE per-market deep-dive on the top-5 finalists.

After Stage 1 (screen) and Stage 2 (enrich → top 5), Stage 3 auto-chains a
per-country deep-dive over the finalists using the engine's FREE, offline layers
only: the competitor snapshot (top exporters), the requirements checklist, and
the zero-network correlation threads. The analysis reaches the terminal
``deepened`` status, each finalist is marked ``stage == 3`` with a ``deepdive``
payload, and the funnel brief flips its Stage-3 line. Every value is real or a
declared gap (I1); the paid observed-prices layer stays structurally out at
``deepen=False`` (I5).
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import MarketSnapshot, WorldTrade

HS6 = "392010"  # the confirmed hs_code on the `product` fixture


def _seed_world(db, hs6=HS6):
    # Six markets whose ISO3 all map to an ISO2 (so the deep-dive runs), one more
    # than the top-5 finalists — the 6th stays Stage 2 (never deep-dived).
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
    resp = client.post(f"/api/v1/products/{product.id}/analysis", headers=auth_headers)
    assert resp.status_code == 202, resp.text
    return resp.json()["analysis"]["id"]


def _run_stage2_autochains_stage3(client, aid, auth_headers) -> None:
    # Stage 2 auto-chains the free Stage-3 deep-dive; under eager mode both ran
    # in-process, so GET carries the deep-dived shortlist.
    res = client.post(f"/api/v1/analyses/{aid}/enrich", headers=auth_headers)
    assert res.status_code == 202, res.text


def test_stage3_auto_chains_to_deepened(client, db, product, auth_headers):
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    _run_stage2_autochains_stage3(client, aid, auth_headers)

    out = client.get(f"/api/v1/analyses/{aid}", headers=auth_headers).json()
    assert out["status"] == "deepened"

    top5 = [r for r in out["rankings"] if r["rank"] <= 5]
    assert len(top5) == 5
    for r in top5:
        assert r["stage"] == 3
        dd = r["deepdive"]
        assert dd is not None
        # The three free deep-dive layers are present.
        assert "competitors" in dd and "requirements" in dd and "threads" in dd
        # correlate returns the SINGULAR thread keys.
        assert "entry_thread" in dd["threads"]
        assert "contacts_thread" in dd["threads"]
        # Requirements rows carry a provenance envelope (value may be a declared gap).
        for req in dd["requirements"]:
            assert "source" in req and "confidence" in req and "note" in req


def test_stage3_brief_flips_stage3_line(client, db, product, auth_headers):
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    _run_stage2_autochains_stage3(client, aid, auth_headers)

    brief = client.get(f"/api/v1/analyses/{aid}/brief", headers=auth_headers).json()
    limits = brief["limits"]
    # The Stage-2 line survives the split.
    assert any("Stage-2 applied tariff" in limit for limit in limits)
    # The Stage-3 line flipped to "applied"; the "not yet applied" caveat is gone.
    assert any("Stage-3 per-market deep-dive applied" in limit for limit in limits)
    assert not any("not yet applied" in limit for limit in limits)


def test_stage3_free_sweep_skips_observed_prices(client, db, product, auth_headers):
    # I5 GUARD — the FREE sweep (deepen=False) builds the offline competitor
    # snapshot (top exporters) but writes NO observed_prices; the paid local-price
    # layer stays structurally skipped, mirroring test_observed_prices' paid-skip.
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    _run_stage2_autochains_stage3(client, aid, auth_headers)

    snaps = db.scalars(select(MarketSnapshot).where(MarketSnapshot.hs_code == HS6)).all()
    assert snaps, "the free deep-dive built market snapshots for the finalists"
    for s in snaps:
        assert not s.observed_prices  # the paid layer never ran (None/empty) — the I5 guard
    # The free competitor layer populated at least the finalist(s) with an offline
    # Comtrade fixture; markets without a fixture are honest declared gaps (empty
    # top_exporters, I1) — not every finalist has one, so assert at least one did.
    assert any(s.top_exporters for s in snaps)


def test_stage3_deepdive_endpoint_requires_confirmed_hs(client, db, product, auth_headers):
    # I2 — the explicit deepdive endpoint keeps the HS-confirm 409 gate.
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    product.hs_confirmed_by_user = False
    db.commit()

    res = client.post(f"/api/v1/analyses/{aid}/deepdive", headers=auth_headers)
    assert res.status_code == 409


def test_stage3_deepdive_endpoint_reruns(client, db, product, auth_headers):
    # The explicit endpoint re-runs Stage 3 on demand and returns 202.
    _seed_world(db)
    aid = _run_stage1(client, product, auth_headers)
    _run_stage2_autochains_stage3(client, aid, auth_headers)

    res = client.post(f"/api/v1/analyses/{aid}/deepdive", headers=auth_headers)
    assert res.status_code == 202, res.text
    assert res.json()["task_id"]

    out = client.get(f"/api/v1/analyses/{aid}", headers=auth_headers).json()
    assert out["status"] == "deepened"

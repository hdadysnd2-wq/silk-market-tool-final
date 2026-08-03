"""The world funnel persists a country shortlist per analysis (Stage 1 → DB).

Extends the transit-port guard (I9) to persisted state: the ranked
``country_rankings`` a report reads must carry the transit-hub flag + penalty
(a re-export hub never silently on top) and the mirror / no-data provenance (I1).
"""

from __future__ import annotations

from app.models import Analysis, CountryRanking, WorldTrade
from app.services.ranking import rank_and_persist
from app.services.world_funnel import MIRROR_TAG, NO_DATA_TAG, TRANSIT_HUB_TAG

HS6 = "080410"
YEAR = 2022


def _seed_world(db):
    rows = [
        ("NLD", 1000.0, True, False),  # transit hub — highest RAW volume
        ("DEU", 700.0, False, False),  # genuine demand
        ("IND", 500.0, False, True),  # mirror-derived
        ("SGP", 400.0, True, False),  # transit hub
        ("XXX", None, False, False),  # failed fetch
    ]
    for iso3, usd, hub, mirror in rows:
        db.add(
            WorldTrade(
                hs6=HS6,
                importer_iso3=iso3,
                year=YEAR,
                import_usd=usd,
                is_transit_hub=hub,
                is_mirror=mirror,
                source="UN Comtrade",
            )
        )
    db.commit()


def _analysis(db) -> Analysis:
    a = Analysis(product_name="dates", status="classified")
    db.add(a)
    db.commit()
    return a


def test_rankings_persisted_with_transit_guard(db):
    _seed_world(db)
    analysis = _analysis(db)

    rankings = rank_and_persist(db, analysis, HS6)
    db.commit()

    stored = list(
        db.query(CountryRanking)
        .filter(CountryRanking.analysis_id == analysis.id)
        .order_by(CountryRanking.rank)
    )
    assert [r.importer_iso3 for r in stored] == ["DEU", "IND", "NLD", "SGP", "XXX"]
    assert stored[0].importer_iso3 == "DEU"  # I9: genuine market tops, not a hub

    nld = next(r for r in stored if r.importer_iso3 == "NLD")
    assert nld.is_transit_hub is True
    assert TRANSIT_HUB_TAG in (nld.tags or [])
    assert nld.rank > stored[0].rank  # penalized below the genuine leader
    assert float(nld.screen_score) < float(nld.import_usd)

    assert all(r.stage == 1 and r.source == "world_trade" for r in stored)
    assert len(rankings) == 5


def test_mirror_and_no_data_provenance_persisted(db):
    _seed_world(db)
    analysis = _analysis(db)
    rank_and_persist(db, analysis, HS6)
    db.commit()

    by_iso = {
        r.importer_iso3: r
        for r in db.query(CountryRanking).filter(CountryRanking.analysis_id == analysis.id)
    }
    assert MIRROR_TAG in (by_iso["IND"].tags or [])
    assert by_iso["XXX"].import_usd is None  # I1 — declared gap, not fabricated
    assert NO_DATA_TAG in (by_iso["XXX"].tags or [])


def test_no_world_data_persists_nothing(db):
    analysis = _analysis(db)
    rankings = rank_and_persist(db, analysis, "999999")
    db.commit()
    assert rankings == []
    assert db.query(CountryRanking).filter(CountryRanking.analysis_id == analysis.id).count() == 0

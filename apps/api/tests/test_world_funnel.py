"""Funnel Stage 1 + transit-port guard (I9).

The named Phase-2 acceptance: a transit hub must appear flagged AND penalized in
a fixture ranking — it must not silently top the list on inflated (re-export)
import volume.
"""

from __future__ import annotations

from app.models import WorldTrade
from app.services.world_funnel import (
    MIRROR_TAG,
    NO_DATA_TAG,
    TRANSIT_HUB_TAG,
    screen_world,
)

HS6 = "080410"
YEAR = 2022


def _seed(db):
    rows = [
        # (iso3, import_usd, is_transit_hub, is_mirror)
        ("NLD", 1000.0, True, False),  # transit hub — highest RAW volume
        ("DEU", 700.0, False, False),  # genuine demand, lower raw volume
        ("IND", 500.0, False, True),  # mirror-derived
        ("SGP", 400.0, True, False),  # transit hub
        ("XXX", None, False, False),  # failed fetch — declared gap
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


def test_transit_hub_is_flagged_and_penalized_not_topping(db):
    _seed(db)
    result = screen_world(db, HS6)

    assert result.year == YEAR
    assert result.total_screened == 5
    order = [m.importer_iso3 for m in result.markets]

    # I9: the raw-volume leader (NLD, a transit hub) is demoted below a genuine
    # market (DEU) after the penalty — it does NOT silently top the ranking.
    assert order[0] == "DEU"
    assert order.index("NLD") > order.index("DEU")

    nld = next(m for m in result.markets if m.importer_iso3 == "NLD")
    assert nld.is_transit_hub is True
    assert TRANSIT_HUB_TAG in nld.tags  # visible flag, not a silent demotion
    assert nld.screen_score < float(nld.import_usd)  # genuinely penalized


def test_mirror_and_no_data_rows_are_tagged(db):
    _seed(db)
    result = screen_world(db, HS6)
    by_iso = {m.importer_iso3: m for m in result.markets}

    assert MIRROR_TAG in by_iso["IND"].tags
    # I1 — a failed fetch is a declared gap (value None, score 0), not a zero.
    assert by_iso["XXX"].import_usd is None
    assert by_iso["XXX"].screen_score == 0.0
    assert NO_DATA_TAG in by_iso["XXX"].tags


def test_growth_lifts_market_of_equal_volume(db):
    # Decision #8 — the multi-year trend feeds the screening score. Two genuine
    # markets of identical volume: the faster-growing one ranks first, and its
    # score is strictly higher (the trend, not luck, broke the volume tie).
    for iso3, cagr in [("KEN", 0.30), ("EGY", 0.0)]:
        db.add(
            WorldTrade(
                hs6=HS6,
                importer_iso3=iso3,
                year=YEAR,
                import_usd=500.0,
                cagr_3y=cagr,
                is_transit_hub=False,
                is_mirror=False,
                source="UN Comtrade",
            )
        )
    db.commit()

    result = screen_world(db, HS6)
    order = [m.importer_iso3 for m in result.markets]
    assert order.index("KEN") < order.index("EGY")

    ken = next(m for m in result.markets if m.importer_iso3 == "KEN")
    egy = next(m for m in result.markets if m.importer_iso3 == "EGY")
    assert ken.screen_score > egy.screen_score


def test_empty_when_no_world_trade_for_hs6(db):
    result = screen_world(db, "999999")
    assert result.year is None
    assert result.total_screened == 0
    assert result.markets == []

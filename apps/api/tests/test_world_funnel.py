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
    SHORTLIST_MAX,
    SHORTLIST_MIN,
    TRANSIT_HUB_TAG,
    screen_world,
    shortlist_quota,
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


# ── J1: the top-20% cut ─────────────────────────────────────────────────────


def _seed_n(db, n: int, hs6: str = "999888"):
    for i in range(n):
        db.add(
            WorldTrade(
                hs6=hs6,
                importer_iso3=f"A{i:02d}",  # synthetic but unique ISO3-shaped codes
                year=YEAR,
                import_usd=1000.0 + i,
                is_transit_hub=False,
                is_mirror=False,
                source="UN Comtrade",
            )
        )
    db.commit()


def test_shortlist_quota_is_top_20_percent_clamped_5_to_30():
    assert shortlist_quota(50) == 10  # ceil(20% of 50)
    assert shortlist_quota(12) == 5  # ceil(2.4)=3 → clamped up to the min
    # Zero coverage is the one case the min-5 floor must NOT lift: every candidate
    # is a declared no-data gap (I1) that scores 0, so shortlisting/enriching 5 of
    # them just burns the Stage-2 API budget on markets that can never rank.
    assert shortlist_quota(0) == 0
    assert shortlist_quota(1) == SHORTLIST_MIN  # thin but real coverage still floors at 5
    assert shortlist_quota(100) == 20
    assert shortlist_quota(1000) == SHORTLIST_MAX  # 200 → clamped to 30
    assert shortlist_quota(26) == 6  # ceil(5.2) — the ceil, not the floor


def test_screen_world_keeps_20_percent_of_50_covered_markets(db):
    _seed_n(db, 50)
    result = screen_world(db, "999888")
    assert result.total_screened == 50
    assert result.covered == 50
    assert result.shortlisted == 10
    assert len(result.markets) == 10


def test_screen_world_small_market_clamps_to_minimum_5(db):
    _seed_n(db, 12)
    result = screen_world(db, "999888")
    assert result.covered == 12
    assert result.shortlisted == 5
    assert len(result.markets) == 5


def test_no_data_rows_do_not_inflate_the_quota_base(db):
    # 10 covered + 40 declared no-data gaps (I1): the 20% base is the COVERED
    # count (quota 5, the clamp floor), not the raw row count (which would be 10).
    _seed_n(db, 10)
    for i in range(40):
        db.add(
            WorldTrade(
                hs6="999888",
                importer_iso3=f"B{i:02d}",
                year=YEAR,
                import_usd=None,
                is_transit_hub=False,
                is_mirror=False,
                source="UN Comtrade",
            )
        )
    db.commit()
    result = screen_world(db, "999888")
    assert result.total_screened == 50
    assert result.covered == 10
    assert result.shortlisted == 5


def test_explicit_top_n_still_overrides_the_quota(db):
    _seed_n(db, 50)
    result = screen_world(db, "999888", top_n=3)
    assert len(result.markets) == 3
    assert result.shortlisted == 3

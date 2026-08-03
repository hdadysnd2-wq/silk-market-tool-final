"""Hermetic tests for the world_trade transform (no pandas, no network)."""

from __future__ import annotations

import etl.world_trade_sync as wt


def test_is_transit_hub_flags_reexport_hubs():
    for hub in ("ARE", "NLD", "SGP", "HKG", "BEL"):
        assert wt.is_transit_hub(hub) is True
    assert wt.is_transit_hub("nld") is True  # case-insensitive
    for non_hub in ("DEU", "USA", "IND", "SAU"):
        assert wt.is_transit_hub(non_hub) is False


def test_compute_yoy_uses_two_most_recent_years():
    assert wt.compute_yoy({2021: 100.0, 2022: 120.0}) == 0.2
    assert wt.compute_yoy({2020: 50.0, 2021: 100.0, 2022: 90.0}) == -0.1


def test_compute_yoy_declares_gap_when_insufficient_or_zero_base():
    assert wt.compute_yoy({2022: 100.0}) is None  # one year
    assert wt.compute_yoy({2021: 0.0, 2022: 100.0}) is None  # zero base
    assert wt.compute_yoy({2021: None, 2022: 100.0}) is None  # missing base


def test_compute_cagr_3y_over_span():
    # 100 -> 200 over 3 years: (2)**(1/3) - 1 ≈ 0.2599
    cagr = wt.compute_cagr_3y({2019: 100.0, 2020: 130.0, 2021: 160.0, 2022: 200.0})
    assert cagr is not None
    assert abs(cagr - (2.0 ** (1 / 3) - 1)) < 1e-9


def test_compute_cagr_3y_none_when_insufficient():
    assert wt.compute_cagr_3y({2022: 100.0}) is None
    assert wt.compute_cagr_3y({2021: 0.0, 2022: 100.0}) is None  # non-positive dropped


def test_build_rows_emits_latest_year_with_flags_and_provenance():
    rows = wt.build_rows(
        "080410",
        {
            "NLD": {2020: 800.0, 2021: 900.0, 2022: 1000.0},  # transit hub
            "DEU": {2021: 600.0, 2022: 700.0},
            "IND": {2022: 500.0},
        },
        source="UN Comtrade",
        fetched_at="2026-01-01",
        mirror_importers={"IND"},
    )
    by_iso = {r["importer_iso3"]: r for r in rows}

    assert by_iso["NLD"]["year"] == 2022
    assert by_iso["NLD"]["import_usd"] == 1000.0
    assert by_iso["NLD"]["is_transit_hub"] is True
    assert by_iso["NLD"]["yoy_growth"] is not None  # 900 -> 1000
    assert by_iso["DEU"]["is_transit_hub"] is False
    assert by_iso["IND"]["is_mirror"] is True
    assert by_iso["IND"]["yoy_growth"] is None  # single year → declared gap (I1)
    # Every row is keyed exactly like the world_trade columns.
    for r in rows:
        assert set(r) == set(wt.WORLD_TRADE_COLUMNS)


def test_build_rows_skips_importers_with_no_usable_data():
    rows = wt.build_rows("080410", {"XXX": {2022: None}})
    assert rows == []

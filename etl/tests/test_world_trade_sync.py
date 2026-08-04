"""Hermetic tests for the world_trade transform (no pandas, no network)."""

from __future__ import annotations

import pytest

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


# --- run() orchestration (fetch → transform → upsert), with injected seams -----
# The heavy fetch (pandas + comtradeapicall) and DB upsert (SQLAlchemy) are lazy
# and unavailable in the etl CI job, so run() is verified with fakes: it must wire
# the fetched series through build_rows into the writer and return the row count.


def test_run_orchestrates_fetch_transform_and_upsert():
    captured: dict = {}

    def fake_fetcher(hs6, years):
        assert hs6 == "080410"
        assert list(years) == [2021, 2022]
        return (
            {
                "NLD": {2021: 900.0, 2022: 1000.0},
                "IND": {2022: 500.0},
            },  # NLD transit hub
            {"NLD": {2022: 5.0}, "IND": {}},
            {"IND"},  # mirror-derived
        )

    def fake_writer(rows):
        captured["rows"] = rows
        return len(rows)

    written = wt.run("080410", [2021, 2022], fetcher=fake_fetcher, writer=fake_writer)

    assert written == 2
    by_iso = {r["importer_iso3"]: r for r in captured["rows"]}
    assert by_iso["NLD"]["is_transit_hub"] is True  # I9 flag survives the pipeline
    assert by_iso["NLD"]["yoy_growth"] is not None  # 900 → 1000
    assert by_iso["NLD"]["import_qty"] == 5.0
    assert by_iso["IND"]["is_mirror"] is True  # I1/I9 provenance from the fetcher
    assert by_iso["NLD"]["source"] == "UN Comtrade"
    assert by_iso["NLD"]["fetched_at"] is not None  # stamped for the year display
    # Every row is upsert-ready (keys match the table columns).
    for row in captured["rows"]:
        assert set(row) == set(wt.WORLD_TRADE_COLUMNS)


def test_run_requires_an_hs6_code():
    with pytest.raises(ValueError):
        wt.run(None, fetcher=lambda *a: ({}, {}, set()), writer=lambda rows: 0)


def test_default_years_are_three_recent_ascending():
    years = wt._default_years()
    assert len(years) == 3
    assert years == sorted(years)
    assert years[-1] - years[0] == 2

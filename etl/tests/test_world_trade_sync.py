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


# ── schema tolerance for the (never-live-verified) Comtrade response ─────────
# The live _fetch_world_imports has never run against the paid API; an unexpected
# column spelling used to silently drop every row (empty coverage read as "the
# world doesn't import this"). resolve_columns tolerates known spellings and a
# truly unknown schema is a declared gap the log names — these lock that.


def test_resolve_columns_matches_documented_comtrade_spelling():
    iso, val, qty = wt.resolve_columns(
        ["period", "reporterISO", "primaryValue", "qty", "cmdCode"])
    assert (iso, val, qty) == ("reporterISO", "primaryValue", "qty")


def test_resolve_columns_is_case_insensitive_and_tolerates_aliases():
    # A capitalised / aliased schema still resolves (spelling drift must not
    # zero out real coverage).
    iso, val, qty = wt.resolve_columns(
        ["ReporterISO", "TradeValue", "primaryQty"])
    assert iso == "ReporterISO"
    assert val == "TradeValue"
    assert qty == "primaryQty"


def test_resolve_columns_reports_missing_mandatory_fields_as_none():
    # No recognizable ISO or value column → both None (caller declares a gap and
    # logs the columns received; it never fabricates or silently drops).
    iso, val, qty = wt.resolve_columns(["reporterCode", "someOtherValue"])
    assert iso is None
    assert val is None
    assert qty is None


def test_resolve_columns_qty_optional_when_iso_and_value_present():
    iso, val, qty = wt.resolve_columns(["reporterISO", "primaryValue"])
    assert iso == "reporterISO" and val == "primaryValue"
    assert qty is None  # qty is genuinely optional, not a hard failure


# ── the library swallows request errors (print + empty df) — we must not ──────
# Live incident 2026-08-08: `world_trade_synced rows=0` with NO error line —
# comtradeapicall print()s "Request error: …" and returns an empty DataFrame
# instead of raising, so the except-branch never fires. These lock the two
# defenses: library stdout becomes a structured WARNING, and empty-but-
# successful years are declared, never silent.


def _fake_comtrade_modules(monkeypatch, print_msg: str):
    import sys
    import types

    class _EmptyDF:
        empty = True
        columns: list[str] = []

    fake_api = types.ModuleType("comtradeapicall")

    def _get_final_data(subscription_key, **kw):
        if print_msg:
            print(print_msg)
        return _EmptyDF()

    fake_api.getFinalData = _get_final_data
    fake_pd = types.ModuleType("pandas")
    fake_pd.isna = lambda v: v != v
    monkeypatch.setitem(sys.modules, "comtradeapicall", fake_api)
    monkeypatch.setitem(sys.modules, "pandas", fake_pd)


def test_swallowed_library_error_is_surfaced_as_structured_warning(
    monkeypatch, caplog
):
    _fake_comtrade_modules(monkeypatch, "Request error: tunnel 403")
    with caplog.at_level("WARNING", logger="etl.world_trade_sync"):
        usd, qty, mirrors = wt._fetch_world_imports("040299", [2023])
    assert usd == {} and qty == {} and mirrors == set()
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "comtrade_call_output" in blob and "tunnel 403" in blob, blob


def test_empty_but_successful_year_is_declared_not_silent(monkeypatch, caplog):
    _fake_comtrade_modules(monkeypatch, "")
    with caplog.at_level("WARNING", logger="etl.world_trade_sync"):
        wt._fetch_world_imports("040299", [2023, 2024])
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert blob.count("comtrade_empty_result") == 2, blob
    assert "hs6=040299" in blob and "year=2023" in blob and "year=2024" in blob

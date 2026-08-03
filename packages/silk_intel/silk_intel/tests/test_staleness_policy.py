"""اختبارات سياسة الحداثة — staleness / TTL policy (persist-4).

يقفل: (١) نوافذ الحداثة لكل نوع بيانات مع ضبط بالبيئة؛ (٢) الإصابة الحديثة
تُخدم fresh بلا تحديث خلفية؛ (٣) العتيقة تُخدم **فوراً** معلَّمة stale (إسناد
+ status) ويُطلَق تحديث بالخلفية يكتب للمخزن؛ (٤) الحالات الأربع متمايزة:
fresh / stale / fetch_failed / no_record — لا تُعرض قيمة مخزّنة كجلب حي،
ولا يُخلط تعذّر الجلب بالغياب الحقيقي.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

import silk_store  # noqa: E402
import silk_data_layer_v2 as v2  # noqa: E402


def _seed(rows):
    silk_store.migrate()
    silk_store.upsert_trade_flows(rows)


def _age_all_rows(iso_ts: str):
    """عتّق كل الصفوف — force retrieved_at to a past timestamp (test-only)."""
    with silk_store.connect() as conn:
        conn.execute("UPDATE trade_flows SET retrieved_at = ?", (iso_ts,))
        conn.commit()


_ROWS = [
    {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "WLD",
     "year": 2023, "flow": "M", "value_usd": 900.0},
    {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "SAU",
     "year": 2023, "flow": "M", "value_usd": 600.0},
]


# ── نوافذ الحداثة · freshness windows ────────────────────────────────────────

def test_freshness_windows_per_kind_and_env_override(monkeypatch):
    assert silk_store.fresh_days("trade") == 90
    assert silk_store.fresh_days("indicator") == 30
    assert silk_store.fresh_days("price") == 7
    monkeypatch.setenv("SILK_FRESH_TRADE_DAYS", "5")
    assert silk_store.fresh_days("trade") == 5
    monkeypatch.setenv("SILK_FRESH_TRADE_DAYS", "junk")
    assert silk_store.fresh_days("trade") == 90          # قيمة فاسدة => الافتراضي


def test_freshness_states():
    assert silk_store.freshness(None) == "unknown"
    assert silk_store.freshness("not-a-date") == "unknown"
    assert silk_store.freshness("2020-01-01") == "stale"
    assert silk_store.freshness("2020-01-01T00:00:00+00:00") == "stale"
    assert silk_store.freshness(silk_store._now()) == "fresh"


# ── الخدمة السريعة + التحديث الخلفي · serve fast, refresh behind ─────────────

def test_fresh_hit_served_without_background_refresh():
    _seed(_ROWS)
    with mock.patch.object(v2, "_refresh_in_background") as bg, block_network():
        got = v2.market_imports_cached("080410", "784", "ARE", 2023)
    bg.assert_not_called()
    assert got["served_from"] == "store" and got["freshness"] == "fresh"
    assert got["total_usd"] == 900.0
    assert all(c.status != "stale" for c in got["competitors"])


def test_stale_hit_served_immediately_flagged_and_refresh_triggered():
    _seed(_ROWS)
    _age_all_rows("2020-01-01T00:00:00+00:00")
    with mock.patch.object(v2, "_refresh_in_background") as bg, block_network():
        got = v2.market_imports_cached("080410", "784", "ARE", 2023)
    bg.assert_called_once()                       # تحديث بالخلفية أُطلق
    assert got["served_from"] == "store" and got["freshness"] == "stale"
    assert got["total_usd"] == 900.0              # القيمة خُدمت فوراً — لا حجب
    assert "أقدم من نافذة الحداثة" in got["provenance_note"]
    assert "جُلبت أصلاً 2020-01-01" in got["provenance_note"]
    assert all(c.status == "stale" for c in got["competitors"])


def test_swr_job_refreshes_store_and_failure_keeps_stale_value():
    _seed(_ROWS)
    _age_all_rows("2020-01-01T00:00:00+00:00")

    def live_ok(hs, m49, year):
        return {"total_usd": 1500.0, "competitors": [v2._competitor_dp(
            "682", 1500.0, 1500.0, hs_code=hs, market_label="ARE", year=year)],
            "xval_note": ""}

    v2._swr_refresh("080410", "784", "ARE", 2023, live=live_ok)
    got = silk_store.market_imports_from_store("080410", "ARE", 2023)
    assert got["total_usd"] == 1500.0             # المخزن تحدّث
    assert silk_store.freshness(got["retrieved_at"], "trade") == "fresh"

    # فشل الجلب الحي: القيمة العتيقة تبقى كما هي — لا حذف ولا اختلاق.
    _age_all_rows("2020-01-01T00:00:00+00:00")
    v2._swr_refresh("080410", "784", "ARE", 2023,
                    live=lambda *a: {"total_usd": None, "competitors": [],
                                     "fetch_failed": True})
    got2 = silk_store.market_imports_from_store("080410", "ARE", 2023)
    assert got2["total_usd"] == 1500.0
    assert silk_store.freshness(got2["retrieved_at"], "trade") == "stale"


def test_swr_kill_switch(monkeypatch):
    monkeypatch.setenv("SILK_SWR", "0")
    with mock.patch("threading.Thread") as t:
        v2._refresh_in_background("080410", "784", "ARE", 2023)
    t.assert_not_called()


# ── تمايز الحالات الأربع · four distinct states ──────────────────────────────

def test_cold_store_fetch_failed_distinct_from_no_record():
    silk_store.migrate()   # مخزن بارد لكن مهيّأ — cold yet migrated store
    # تعذّر الجلب (شبكة مقطوعة) — fetch_failed معلن، لا صفوف تُكتب.
    with block_network():
        got = v2.market_imports_cached("080410", "784", "ARE", 2023)
    assert got["served_from"] == "live"
    assert got.get("fetch_failed") is True and got["total_usd"] is None
    assert silk_store.market_imports_from_store("080410", "ARE", 2023)[
        "total_usd"] is None                      # الفشل لا يلوّث المخزن

    # غياب حقيقي (ردّ ناجح بلا سجلات) — لا fetch_failed.
    got2 = v2.market_imports_cached(
        "080410", "784", "ARE", 2023,
        live=lambda *a: {"total_usd": None, "competitors": []})
    assert got2["served_from"] == "live"
    assert "fetch_failed" not in got2 and got2["total_usd"] is None


def test_tradeflow_flags_stale_world_row():
    _seed([{"hs6": "040900", "reporter_iso3": "KWT", "partner_iso3": "WLD",
            "year": 2023, "flow": "M", "value_usd": 789206.0}])
    _age_all_rows("2020-01-01T00:00:00+00:00")
    from silk_agents import TradeFlowAgent
    with block_network():
        rep = TradeFlowAgent().run({"hs_code": "040900", "market_m49": "414",
                                    "iso3": "KWT", "year": 2023})
    m = [f for f in rep.findings if f.value is not None][0]
    assert m.status == "stale" and "أقدم من نافذة الحداثة" in m.note
    assert m.retrieved_at.startswith("2020-01-01")   # تاريخ الجلب الأصلي محفوظ

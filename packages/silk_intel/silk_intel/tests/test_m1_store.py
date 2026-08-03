"""اختبارات M1 — المخزن الموحّد + الترحيلات + استيراد الإرث (§3 من الخطة).

كلها معزولة (SQLite مؤقت، صفر شبكة). تقفل:
1. migrate() ينشئ كل الجداول ويعيد التشغيل بلا أثر (idempotent).
2. CRUD مخزن الحقائق: upsert مؤشر (الأحدث يفوز)، تدفقات تجارية بقيد فريد،
   market_imports_from_store بلا اختلاق (لا صفوف => total None).
3. تحليلات: حفظ blob + إسقاطات مسطّحة، ترقيم بمؤشر، قرار بقيد verdict،
   نتيجة فعلية upsert (False لتحليل غائب).
4. مستخدمون: قيد الدور يرفض قيمة خارج admin/analyst/viewer.
5. استيراد الإرث من silk_storage القديم: المنتج/الأسواق/النتيجة تُنقل،
   وإعادة التشغيل تتجاوز المستورد (idempotent).
"""
import contextlib
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.contextmanager
def _tmp_store():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "store.db")
    saved = os.environ.get("SILK_STORE_DB")
    os.environ["SILK_STORE_DB"] = path
    try:
        import silk_store
        silk_store.migrate()
        yield silk_store, path
    finally:
        if saved is None:
            os.environ.pop("SILK_STORE_DB", None)
        else:
            os.environ["SILK_STORE_DB"] = saved


def test_migrate_creates_schema_and_is_idempotent():
    with _tmp_store() as (store, path):
        first = store.migrate()      # already applied inside fixture
        assert first == []           # إعادة التشغيل لا تعيد التطبيق
        con = sqlite3.connect(path)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for t in ("users", "sessions", "api_keys", "markets", "indicators",
                  "trade_flows", "collection_runs", "analyses",
                  "analysis_markets", "decisions", "reports", "outcomes",
                  "schema_migrations"):
            assert t in tables, f"missing table {t}"


def test_indicator_upsert_newest_wins_and_lookup():
    with _tmp_store() as (store, _):
        store.upsert_indicator("ARE", "SP.POP.TOTL", 2024, 9_900_000,
                               "World Bank", 0.95, "first")
        store.upsert_indicator("ARE", "SP.POP.TOTL", 2024, 10_986_400,
                               "World Bank", 0.95, "corrected")
        row = store.get_indicator("ARE", "SP.POP.TOTL", 2024)
        assert row["value"] == 10_986_400 and row["note"] == "corrected"
        # year=None → أعلى سنة
        store.upsert_indicator("ARE", "SP.POP.TOTL", 2020, 9_000_000,
                               "World Bank", 0.95, "old")
        latest = store.get_indicator("ARE", "SP.POP.TOTL")
        assert latest["year"] == 2024


def test_trade_flows_upsert_and_market_imports_no_fabrication():
    with _tmp_store() as (store, _):
        n = store.upsert_trade_flows([
            {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "SAU",
             "year": 2023, "flow": "M", "value_usd": 1.0e8},
            {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "IRQ",
             "year": 2023, "flow": "M", "value_usd": 7.8e7},
        ])
        assert n == 2
        got = store.market_imports_from_store("080410", "ARE", 2023)
        assert got["total_usd"] == 1.78e8 and len(got["partners"]) == 2
        assert got["partners"][0]["iso3"] == "SAU"     # مرتّبة تنازلياً
        # لا صفوف => لا اختلاق
        empty = store.market_imports_from_store("080410", "MAR", 2023)
        assert empty["total_usd"] is None and empty["partners"] == []


def test_analysis_save_projections_pagination_decision_outcome():
    with _tmp_store() as (store, _):
        result = {"product": "تمور", "hs_code": "080410", "year": 2023,
                  "markets": [
                      {"iso3": "ARE", "total_score": 0.81, "confidence": 0.75,
                       "components": {"market_size": {"value": 2.7e8},
                                      "saudi_position": {"value": 38}}},
                      {"iso3": "MAR", "total_score": 0.60, "confidence": 0.5,
                       "components": {}}]}
        a1 = store.save_analysis(result)
        a2 = store.save_analysis(result)
        got = store.get_analysis(a1)
        assert got["result"]["product"] == "تمور" and got["hs6"] == "080410"
        page = store.list_analyses(limit=1)
        assert [r["id"] for r in page] == [a2]
        page2 = store.list_analyses(limit=5, after_id=a2)
        assert [r["id"] for r in page2] == [a1]          # ترقيم بمؤشر يعمل
        # الإسقاطات المسطّحة
        import sqlite3 as s3
        con = s3.connect(os.environ["SILK_STORE_DB"])
        rows = con.execute("SELECT iso3, rank, comp_market_size FROM "
                           "analysis_markets WHERE analysis_id=? ORDER BY rank",
                           (a1,)).fetchall()
        assert rows[0][0] == "ARE" and rows[0][2] == 2.7e8
        # قرار بقيد verdict
        did = store.save_decision(a1, "ARE", "CONDITIONAL-GO", 0.55, 0.5,
                                  pillars={"market": 0.8, "regulatory": None},
                                  conditions=["استكمال الحلال"])
        assert did > 0
        import pytest
        with pytest.raises(Exception):
            store.save_decision(a1, "ARE", "MAYBE", 0.5, 0.5)   # قيمة خارج القيد
        # النتيجة الفعلية
        assert store.set_outcome(a1, "launched") is True
        assert store.set_outcome(a1, "launched-v2") is True     # upsert
        assert store.set_outcome(999999, "x") is False          # تحليل غائب


def test_user_role_constraint():
    with _tmp_store() as (store, _):
        uid = store.create_user("a@silk.sa", "admin", "Admin")
        assert store.get_user_by_email("A@SILK.SA")["id"] == uid  # normalized
        import pytest
        with pytest.raises(Exception):
            store.create_user("b@silk.sa", "superuser")           # دور غير مسموح


def test_legacy_import_moves_analyses_and_outcomes_idempotently():
    import silk_storage
    with _tmp_store() as (store, _):
        d = tempfile.mkdtemp()
        old = os.path.join(d, "silk.db")
        silk_storage.init_db(old)
        legacy_result = {"product": "عسل", "hs_code": "040900", "year": 2023,
                         "preliminary": True, "classified": True,
                         "markets": [{"iso3": "ARE", "country": "الإمارات",
                                      "total_score": 0.7, "confidence": 0.6,
                                      "components": {}}]}
        lid = silk_storage.save_analysis(legacy_result, path=old)
        silk_storage.set_outcome(lid, "entered market", path=old)

        sys.path.insert(0, os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))), "tools"))
        import import_legacy
        stats = import_legacy.import_legacy(old)
        assert stats["imported"] == 1 and stats["outcomes"] == 1
        rows = store.list_analyses()
        assert rows[0]["product"] == "عسل" and rows[0]["legacy_id"] == lid
        got = store.get_analysis(rows[0]["id"])
        assert got["result"]["hs_code"] == "040900"
        # إعادة التشغيل: تجاوز لا تكرار
        stats2 = import_legacy.import_legacy(old)
        assert stats2["imported"] == 0 and stats2["skipped"] == 1
        assert len(store.list_analyses()) == 1

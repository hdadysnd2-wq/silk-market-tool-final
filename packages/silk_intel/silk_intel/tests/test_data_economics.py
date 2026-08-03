"""اختبارات اقتصاد البيانات — cost/usage visibility (persist-5).

يقفل: (١) عدّاد لكل تحليل يفرّق إصابة المخزن / إصابة ذاكرة الطلبات / الجلب
الحي؛ (٢) المحرّك يرفق اللقطة في النتيجة والقالب يمرّرها؛ (٣) الأرقام مرصودة
(عدّ أحداث فعلية) والنسبة قسمة معلنة؛ (٤) خارج سياق العدّاد كل شيء يعمل
كما كان — العدّ شفافية لا شرط.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

import silk_context  # noqa: E402
import silk_store  # noqa: E402


def test_counter_lifecycle_and_isolation():
    c1 = silk_context.begin_data_counter()
    silk_context.count_data("store_hits")
    silk_context.count_data("cache_hits", 2)
    assert silk_context.data_counter() == {
        "store_hits": 1, "cache_hits": 2, "live_fetches": 0,
        "llm_calls": 0, "tool_calls": 0, "llm_usage": {}}
    c2 = silk_context.begin_data_counter()   # تشغيلة جديدة = عدّاد جديد
    assert c2 == {"store_hits": 0, "cache_hits": 0, "live_fetches": 0,
                  "llm_calls": 0, "tool_calls": 0, "llm_usage": {}}
    assert c1["store_hits"] == 1             # الأول لم يُمسّ


def test_llm_and_tool_call_counters():
    # V5 wave 1: silk_llm_runtime يعدّ نداءات كلود/الأدوات في نفس العدّاد.
    silk_context.begin_data_counter()
    silk_context.count_data("llm_calls")
    silk_context.count_data("tool_calls", 3)
    c = silk_context.data_counter()
    assert c["llm_calls"] == 1
    assert c["tool_calls"] == 3


def test_count_data_noop_without_counter():
    silk_context._data_counter.set(None)
    silk_context.count_data("store_hits")    # لا عدّاد => لا انفجار، لا أثر
    assert silk_context.data_counter() is None


def test_cached_get_counts_cache_hit_and_live_fetch(monkeypatch, tmp_path):
    monkeypatch.setenv("SILK_CACHE_DIR", str(tmp_path))
    import silk_cache

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    counter = silk_context.begin_data_counter()
    silk_cache.cached_get("https://x.example/a", {"q": 1},
                          fetcher=lambda u, p: _Resp())
    assert counter["live_fetches"] == 1 and counter["cache_hits"] == 0
    silk_cache.cached_get("https://x.example/a", {"q": 1},
                          fetcher=lambda u, p: _Resp())
    assert counter["live_fetches"] == 1 and counter["cache_hits"] == 1


def test_store_hit_counted_in_market_imports_cached():
    silk_store.migrate()
    silk_store.upsert_trade_flows([
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 900.0},
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 600.0}])
    import silk_data_layer_v2 as v2
    counter = silk_context.begin_data_counter()
    with block_network():
        v2.market_imports_cached("080410", "784", "ARE", 2023)
    assert counter["store_hits"] == 1 and counter["live_fetches"] == 0


def test_engine_attaches_economics_and_view_passes_through():
    silk_store.migrate()
    silk_store.upsert_trade_flows([
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 900.0},
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 600.0}])
    import silk_engine
    from silk_render import build_view, render_text
    with block_network():
        res = silk_engine.analyze("تمور", countries=[{"iso3": "ARE",
                                                      "m49": "784"}],
                                  year=2023)
    de = res["data_economics"]
    assert de["store_hits"] > 0                     # المخزن المبذور خدم فعلاً
    assert "من المخزن/ذاكرة الطلبات" in de["note"]
    served = de["store_hits"] + de["cache_hits"]
    total = served + de["live_fetches"]
    assert f"{round(100 * served / total)}%" in de["note"]  # قسمة معلنة
    view = build_view(res)
    assert view["data_economics"] == de             # القالب يمرّرها كما هي
    assert "اقتصاد البيانات:" in render_text(view)


def test_unclassified_result_still_carries_economics():
    import silk_engine
    with block_network():
        res = silk_engine.analyze("منتج لا وجود له إطلاقاً xyz")
    assert res["classified"] is False
    assert "data_economics" in res and "note" in res["data_economics"]

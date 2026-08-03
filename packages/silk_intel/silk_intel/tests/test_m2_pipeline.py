"""اختبارات M2 — خطّ البيانات: TTL لكل مصدر، مخزن-أولاً، جامعان بميزانية (§4).

كلها معزولة (شبكة مقطوعة/مقلَّدة، SQLite مؤقت). تقفل:
1. سياسة TTL: سنة تجارية مقفلة = 30 يوماً؛ البنك الدولي = 7 أيام.
2. market_imports_cached: إصابة المخزن = صفر نداء حي؛ الإخفاق = مسار حي + كتابة
   عابرة تجعل التشغيل التالي دافئاً. لا اختلاق: مخزن فارغ + حي فاشل = None.
3. collect_worldbank: الجلب الجماعي يكتب مؤشرات موسومة؛ الفشل يسقط للّقطة
   الحقيقية المضمّنة (قيم فعلية بمصدر «لقطة») — لا صمت ولا اختلاق.
4. collect_comtrade: الميزانية اليومية صلبة (النافد يُتخطى مُعلناً في
   collection_runs)، والنتائج تُكتب لمخزن الحقائق.
"""
import contextlib
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_data_layer import DataPoint  # noqa: E402


@contextlib.contextmanager
def _tmp_store():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "store.db")
    saved = os.environ.get("SILK_STORE_DB")
    os.environ["SILK_STORE_DB"] = path
    try:
        import silk_store
        silk_store.migrate()
        yield silk_store
    finally:
        if saved is None:
            os.environ.pop("SILK_STORE_DB", None)
        else:
            os.environ["SILK_STORE_DB"] = saved


def test_ttl_policy_per_source():
    # سنة مقفلة (2022) => TTL شهر؛ البنك الدولي => أسبوع. نلتقط ttl الممرَّر فعلاً.
    import silk_data_layer as dl
    seen = {}

    def spy(url, params, ttl_seconds=86400, fetcher=None):
        seen[url.split("/")[2]] = ttl_seconds
        return None  # cache miss -> يسقط للمسار الحي (مقطوع أدناه)

    with mock.patch("silk_cache.cached_get", spy), \
         mock.patch.object(dl, "_http_get",
                           side_effect=OSError("net blocked")):
        dl.comtrade_trade("080410", "784", 2022, flow="M", partner="all")
        dl.world_bank("ARE", "SP.POP.TOTL")
    assert seen["comtradeapi.un.org"] == 30 * 86400     # سنة مقفلة: شهر
    assert seen["api.worldbank.org"] == 7 * 86400        # البنك الدولي: أسبوع


def test_market_imports_cached_store_hit_means_zero_live_calls():
    with _tmp_store() as store:
        store.upsert_trade_flows([
            {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "WLD",
             "year": 2023, "flow": "M", "value_usd": 2.7e8},
            {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "SAU",
             "year": 2023, "flow": "M", "value_usd": 1.0e8},
        ])
        import silk_data_layer_v2 as v2
        with mock.patch.object(v2, "market_imports",
                               side_effect=AssertionError("live path called")) as live:
            got = v2.market_imports_cached("080410", "784", "ARE", 2023)
        assert live.call_count == 0                      # صفر نداء حي — إصابة مخزن
        assert got["total_usd"] == 2.7e8
        assert got["competitors"][0].value["value_usd"] == 1.0e8
        assert "مخزن" in got["competitors"][0].source     # مصدر موسوم بالمخزن


def test_market_imports_cached_miss_writes_through_then_hits():
    with _tmp_store() as store:
        import silk_data_layer_v2 as v2
        live_payload = {"total_usd": 9.5e7, "competitors": [DataPoint(
            value={"partner": "Tunisia", "code": "788", "value_usd": 3.9e7,
                   "share": 41.0},
            source="UN Comtrade", confidence=0.9, note="live", retrieved_at="t")]}
        with mock.patch.object(v2, "market_imports", return_value=live_payload):
            got1 = v2.market_imports_cached("080410", "504", "MAR", 2023)
        assert got1["total_usd"] == 9.5e7
        rows = store.market_imports_from_store("080410", "MAR", 2023)
        assert rows["total_usd"] == 9.5e7                 # الكتابة العابرة حصلت
        assert rows["partners"][0]["iso3"] == "TUN"       # m49 -> iso3 مُطبَّق
        # التشغيلة الثانية دافئة: المسار الحي ممنوع ويجب ألا يُستدعى.
        with mock.patch.object(v2, "market_imports",
                               side_effect=AssertionError("live called")) as live:
            got2 = v2.market_imports_cached("080410", "504", "MAR", 2023)
        assert live.call_count == 0 and got2["total_usd"] == 9.5e7
        # لا اختلاق: مخزن فارغ + حي فاشل = None/[]
        with mock.patch.object(v2, "market_imports",
                               return_value={"total_usd": None, "competitors": []}):
            empty = v2.market_imports_cached("080410", "818", "EGY", 2023)
        assert empty["total_usd"] is None and empty["competitors"] == []


def test_collect_worldbank_bulk_writes_and_seed_fallback():
    with _tmp_store() as store:
        import silk_collectors as col
        bulk = [None, [
            {"countryiso3code": "ARE", "date": "2024", "value": 10986400},
            {"countryiso3code": "EGY", "date": "2024", "value": 116538258},
            {"countryiso3code": "", "date": "2024", "value": 1},        # يُهمل
            {"countryiso3code": "MAR", "date": "2024", "value": None},  # يُهمل
        ]]
        ok = mock.MagicMock()
        ok.raise_for_status.return_value = None
        ok.json.return_value = bulk
        with mock.patch("requests.get", return_value=ok):
            out = col.collect_worldbank(indicators=["SP.POP.TOTL"])
        assert out == {"fetched": 1, "failed": 0, "seeded": 0}
        row = store.get_indicator("ARE", "SP.POP.TOTL", 2024)
        assert row["value"] == 10986400 and row["source"] == "World Bank"

        # الفشل => بذور حقيقية موسومة (لقطة) لا صمت.
        with mock.patch("requests.get", side_effect=OSError("net blocked")):
            out2 = col.collect_worldbank(indicators=["SP.POP.TOTL"])
        assert out2["failed"] == 1 and out2["seeded"] > 0
        seeded = store.get_indicator("SAU", "SP.POP.TOTL")
        assert seeded and seeded["value"] > 1_000_000
        assert "لقطة" in seeded["source"]                 # provenance = bundled snapshot


def test_collect_comtrade_budget_is_hard_and_writes_flows():
    with _tmp_store() as store:
        import silk_collectors as col
        recs = [{"partnerCode": "0", "primaryValue": 2.7e8},
                {"partnerCode": "682", "primaryValue": 1.0e8}]
        targets = [{"iso3": "ARE", "m49": "784"}, {"iso3": "MAR", "m49": "504"},
                   {"iso3": "EGY", "m49": "818"}]
        with mock.patch.dict(os.environ, {"COMTRADE_DAILY_BUDGET": "2"}), \
             mock.patch("silk_data_layer.comtrade_trade", return_value=recs):
            out = col.collect_comtrade("080410", targets, 2023, pace_seconds=0)
        assert out["fetched"] == 2 and out["skipped_budget"] == 1   # سقف صلب
        got = store.market_imports_from_store("080410", "ARE", 2023)
        assert got["total_usd"] == 2.7e8                            # WLD row
        assert got["partners"][0]["iso3"] == "SAU"                  # 682 -> SAU
        # سجلّ التشغيلة يوثّق التخطي — the run row declares the deferral.
        with store.connect() as conn:
            note = conn.execute("SELECT note FROM collection_runs WHERE "
                                "source='comtrade' ORDER BY id DESC LIMIT 1"
                                ).fetchone()[0]
        assert "skipped_budget=1" in note

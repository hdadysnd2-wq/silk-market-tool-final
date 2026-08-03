"""اختبارات دخان بلا شبكة — تتحقق من الاستيراد، التصنيف، والمبدأ التأسيسي (لا اختلاق بيانات).
Offline smoke tests: imports, HS classification, and the no-fabrication principle.
Run:  python3 -m pytest tests/ -q   (or)  python3 tests/test_smoke.py
"""
import contextlib
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_hs_resolver as resolver
import silk_engine as engine

# نسخة محلية موحَّدة إلى المرجع القانوني الواحد في conftest.py — بلاغ حي
# (تسريب اتصال مجمَّع عبر جلسة requests المشتركة في CI): النسخ المحلية
# المكرَّرة (سبع ملفات) كانت تفتقر لإغلاق تجمّع الاتصالات، فتنجو اتصالات
# حيّة من نداءات سابقة غير محظورة إلى اختبار يُفترض به حجب كامل.
from conftest import block_network as _block_network


def test_all_modules_import():
    import silk_data_layer, silk_data_layer_v2, silk_agents, silk_market_ranker  # noqa: F401


def test_resolver_real_hs_codes():
    assert resolver.resolve("تمور").value == "080410"
    assert resolver.resolve("saffron").value == "091020"
    # كلمة بلا معنى => لا تصنيف ولا اختلاق رمز
    miss = resolver.resolve("xqzwv nonsense 123")
    assert miss.value is None and miss.confidence == 0.0


def test_engine_pipeline_offline_no_fabrication():
    # بلا شبكة: المحرّك يصنّف المنتج لكن لا يخترع أرقام أسواق
    with _block_network():
        res = engine.analyze("تمور", countries=[{"iso3": "ARE", "m49": "784"}], year=2022)
    assert res["classified"] is True
    assert res["hs_code"] == "080410"
    assert res["preliminary"] is True
    row = res["markets"][0]
    assert row["total_score"] == 0.0 and row["confidence"] == 0.0  # no data => no invented score


def test_storage_round_trip(tmp_path=None):
    # خزّن نتيجة وهمية ثم استرجعها — save a fake result, then get it back unchanged.
    import os
    import tempfile
    import silk_storage as storage

    db = os.path.join(tempfile.mkdtemp(), "smoke.db")
    fake = {"product": "demo", "hs_code": "000000", "year": 2022,
            "preliminary": True,
            "markets": [{"country": "Demo-Land", "iso3": "XXX",
                         "total_score": 0.0, "confidence": 0.0}]}
    aid = storage.save_analysis(fake, db)
    got = storage.get_analysis(aid, db)
    assert got is not None and got["product"] == "demo"
    assert any(r["id"] == aid for r in storage.list_analyses(db))


def test_quality_flags_near_zero():
    # صف بحجم سوق شبه صفري => تنبيه عدم تطابق — near-zero size flags a mismatch.
    import silk_quality as quality

    row = {"country": "X", "iso3": "XXX",
           "components": {"market_size": {"value": 12.0},
                          "saudi_position": {"value": 3.0},
                          "demand_capacity": {"value": 1.0e9},
                          "competition": {"value": 0.4}}}
    flags = quality.validate_market_row(row)
    assert any("near-zero" in f for f in flags)


def test_engine_optional_layers_offline():
    # كل الطبقات الاختيارية مفعّلة بلا شبكة: لا تعطّل، يبقى التصنيف سليمًا.
    import os
    import tempfile

    db = os.path.join(tempfile.mkdtemp(), "engine.db")
    with _block_network():
        res = engine.analyze("تمور", countries=[{"iso3": "ARE", "m49": "784"}],
                             year=2022, with_trends=True, with_tariffs=True,
                             persist=True, db_path=db)
    assert res["classified"] is True and res["hs_code"] == "080410"
    assert "quality_flags" in res["markets"][0]      # quality on by default
    assert "analysis_id" in res                       # persisted
    # طبقات السياق مرفقة (قيم None بلا شبكة، لا اختلاق) — context attached, None offline.
    assert "trends" in res["markets"][0] and "tariff" in res["markets"][0]
    assert res["markets"][0]["total_score"] == 0.0    # additive context, score unchanged


def test_api_imports_without_fastapi():
    # api.py يُستورد بلا fastapi — import works offline; app may be None.
    import api
    assert hasattr(api, "create_app") and hasattr(api, "app")


def test_api_deepen_endpoint_own_price_offline():
    # الموجة ٢: الطبقات المدفوعة انتقلت لمسار /deepen — نفس ضمانات اللااختلاق.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")  # TestClient needs it; test-only dep, not a runtime one
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    import api

    assert api.app is not None
    client = TestClient(api.app)
    # لا نستخدم _block_network هنا: تعطّل socket.socket عالمياً يكسر نقل TestClient
    # الداخلي (asyncio socketpair)؛ بدلاً منها نعطّل requests.get فقط — نفس الأثر
    # الحتمي (لا شبكة => لا بيانات) بلا التصادم مع بنية الاختبار التحتية.
    with patch("requests.sessions.Session.request", side_effect=OSError("network disabled for hermetic test")):
        r = client.post("/deepen", json={
            "product": "تمور", "year": 2022,
            "with_localprice": True, "own_price": 25.0,
        })
    assert r.status_code == 200
    data = r.json()
    assert data["classified"] is True and data["hs_code"] == "080410"
    row = data["markets"][0]
    assert "price_comparison" in row
    assert row["price_comparison"]["your_price"] == 25.0
    assert row["price_comparison"]["listings_count"] == 0     # no network -> no listings
    assert row["price_comparison"]["cheaper_than_pct"] is None  # never fabricated


def test_faostat_agent_imports():
    # وكيل فاوستات يُستورد بلا شبكة — offline import + graceful None on unknown area.
    import silk_faostat_agent as fao
    dp = fao.per_capita_supply("XXX", "Dates")
    assert dp.value is None and dp.confidence == 0.0  # no fabrication


def test_cache_returns_none_offline():
    # ذاكرة التخزين تُعيد None بلا شبكة — cached_get degrades to None offline.
    import silk_cache
    with _block_network():
        out = silk_cache.cached_get("https://example.invalid/none", {"a": "1"})
    assert out is None


def test_new_agents_import_and_no_fabrication_keyless():
    # الوكلاء الأربعة الجدد يُستوردون بلا شبكة/مفتاح، وكل نداء بلا مفتاح => value=None.
    import silk_maps_agent, silk_websearch_agent, silk_volza_agent, silk_explee_agent

    with _block_network():
        for key in ("GOOGLE_MAPS_API_KEY", "SEARCH_API_KEY",
                    "VOLZA_API_KEY", "EXPLEE_API_KEY"):
            os.environ.pop(key, None)  # ensure keyless
        dps = [
            silk_maps_agent.find_places("dates morocco")[0],
            silk_websearch_agent.web_search("dates demand")[0],
            silk_volza_agent.importers_by_name("080410", "156")[0],
            silk_explee_agent.discover_buyers("dates packaging", "DEU")[0],
        ]
    for dp in dps:
        assert dp.value is None and dp.confidence == 0.0  # no fabrication keyless


def test_comtrade_endpoint_switches_with_key():
    # بلا مفتاح -> معاينة محدودة؛ مع مفتاح -> endpoint الإنتاج الكامل /data/v1/get.
    import silk_data_layer as d

    saved = d.COMTRADE_KEY
    try:
        d.COMTRADE_KEY = ""
        assert d._comtrade_url().endswith("/public/v1/preview/C/A/HS")
        d.COMTRADE_KEY = "SAMPLEKEY"
        assert d._comtrade_url().endswith("/data/v1/get/C/A/HS")
    finally:
        d.COMTRADE_KEY = saved


def test_market_imports_one_call_size_and_competitors():
    # نداء Comtrade واحد يعطي حجم السوق (صفّ العالم) والمنافسين معًا — no 2nd call.
    import silk_data_layer_v2 as v2

    fake = [
        {"partnerCode": 0, "primaryValue": 241000000.0},   # World = market size
        {"partnerCode": 788, "primaryValue": 75700000.0},  # Tunisia
        {"partnerCode": 682, "primaryValue": 28900000.0},  # Saudi
    ]
    orig = v2.comtrade_trade
    v2.comtrade_trade = lambda *a, **k: [dict(r) for r in fake]
    try:
        mi = v2.market_imports("080410", "504", 2023)
    finally:
        v2.comtrade_trade = orig
    assert mi["total_usd"] == 241000000.0            # World row -> market size
    assert len(mi["competitors"]) == 2               # partners only (World dropped)
    assert mi["competitors"][0].value["partner"]     # named, ranked desc
    shares = sum(c.value["share"] for c in mi["competitors"])
    assert 99.0 <= shares <= 101.0                   # shares ~100% of suppliers


def test_localprice_agent_no_fabrication_keyless():
    # وكيل أسعار السوق المحلي يُستورد بلا شبكة/مفتاح، وكل نداء بلا مفتاح => value=None.
    import silk_localprice_agent as lp

    os.environ.pop("LOCALPRICE_API_KEY", None)
    with _block_network():
        rep = lp.LocalPriceAgent().run({"query": "تمور", "market": "ma"})
    assert rep.failed is True
    dp = rep.findings[0]
    assert dp.value is None and dp.confidence == 0.0  # no fabricated price


def test_engine_localprice_layer_offline():
    # طبقة السعر المحلي مفعّلة بلا شبكة/مفتاح: لا تعطّل، تبقى النتيجة مبدئية بلا اختلاق.
    os.environ.pop("LOCALPRICE_API_KEY", None)
    with _block_network():
        res = engine.analyze("تمور", countries=[{"iso3": "ARE", "m49": "784"}],
                             year=2023, with_localprice=True)
    assert res["classified"] is True and res["year"] == 2023
    assert "localprice" in res["markets"][0]            # context attached
    assert res["markets"][0]["total_score"] == 0.0      # additive, score unchanged


def test_engine_localprice_own_price_offline():
    # own_price مفعّل بلا شبكة: price_comparison مرفق لكن بلا اختلاق (لا قوائم).
    os.environ.pop("LOCALPRICE_API_KEY", None)
    with _block_network():
        res = engine.analyze("تمور", countries=[{"iso3": "ARE", "m49": "784"}],
                             year=2023, with_localprice=True, own_price=25.0)
    row = res["markets"][0]
    pc = row["price_comparison"]
    assert pc["your_price"] == 25.0 and pc["listings_count"] == 0
    assert pc["cheaper_than_pct"] is None and pc["market_avg"] is None  # no fabrication


def test_compare_own_price_no_fabrication_without_listings():
    import silk_localprice_agent as lp

    out = lp.compare_own_price(25.0, [])
    assert out["listings_count"] == 0
    assert out["market_avg"] is None and out["cheaper_than_pct"] is None
    assert out["verdict"] is None


def test_compare_own_price_no_own_price_given():
    import silk_localprice_agent as lp
    from silk_data_layer import DataPoint

    findings = [DataPoint({"price": 100}, "Local retail", 0.6, ""),
                DataPoint({"price": 80}, "Local retail", 0.6, "")]
    out = lp.compare_own_price(None, findings)
    assert out["your_price"] is None and out["listings_count"] == 2
    assert out["market_min"] == 80 and out["market_max"] == 100
    assert out["cheaper_than_pct"] is None and out["verdict"] is None  # not guessed


def test_compare_own_price_percentile_math():
    import silk_localprice_agent as lp
    from silk_data_layer import DataPoint

    findings = [DataPoint({"price": 100}, "Local retail", 0.6, ""),
                DataPoint({"price": 80}, "Local retail", 0.6, ""),
                DataPoint({"price": 60}, "Local retail", 0.6, "")]
    out = lp.compare_own_price(70.0, findings)
    assert out["listings_count"] == 3
    assert out["market_min"] == 60 and out["market_max"] == 100
    assert out["market_avg"] == 80.0
    # سعرك 70 أرخص من قائمتين (80، 100) من أصل 3 => 66.7%
    assert out["cheaper_than_pct"] == round(200 / 3, 1)
    assert "66.7" in out["verdict"]


def test_localprice_bestseller_badge_real_only():
    # الشارة تُقرأ فقط من ردّ المزوّد الحقيقي — لا تُخمَّن من السعر/الترتيب.
    import silk_localprice_agent as lp

    payload = {"shopping_results": [
        {"title": "A", "price": 10, "tag": "Best Seller"},
        {"title": "B", "price": 12, "extensions": ["Free shipping", "Bestseller"]},
        {"title": "C", "price": 8, "bestseller": True},
        {"title": "D", "price": 15},
    ]}
    listings = lp._extract(payload)
    flags = {it["title"]: it["is_best_seller"] for it in listings}
    assert flags == {"A": True, "B": True, "C": True, "D": False}


def test_engine_paid_layers_offline():
    # الطبقات الأربع الجديدة مفعّلة بلا شبكة/مفتاح: لا تعطّل، يبقى التصنيف سليمًا.
    with _block_network():
        for key in ("GOOGLE_MAPS_API_KEY", "SEARCH_API_KEY",
                    "VOLZA_API_KEY", "EXPLEE_API_KEY"):
            os.environ.pop(key, None)
        res = engine.analyze("تمور", countries=[{"iso3": "ARE", "m49": "784"}],
                             year=2022, with_maps=True, with_websearch=True,
                             with_volza=True, with_explee=True)
    assert res["classified"] is True and res["hs_code"] == "080410"
    row = res["markets"][0]
    # طبقات السياق مرفقة (None بلا مفتاح/شبكة، لا اختلاق) — attached, None offline.
    assert "maps" in row and "volza" in row and "explee" in row
    assert "websearch" in res                            # top-level web search
    assert row["total_score"] == 0.0                     # additive, score unchanged


def test_hs_codes_grew_and_resolve_dates():
    # نمت رموز HS وما زال التمر يُصنّف صحيحًا — table grew; dates still resolve.
    assert len(resolver.load_hs_codes()) >= 157
    assert resolver.resolve("تمور").value == "080410"


def test_rank_markets_has_dashboard_fields():
    # حقول لوحة المعلومات الإضافية موجودة (قد تكون None بلا شبكة، لا اختلاق).
    import silk_market_ranker as ranker

    with _block_network():
        ranked = ranker.rank_markets("080410",
                                     countries=[{"iso3": "ARE", "m49": "784"}],
                                     year=2022)
    row = ranked[0]
    for key in ("income_ppp", "population", "top_competitor"):
        assert key in row  # additive key present (value may be None offline)


def test_tradeflow_missing_primary_value_not_summed_as_zero():
    # سجل كومتريد بلا primaryValue لا يُجمع كصفر — المجموع من القيم الحقيقية فقط،
    # والإسقاط مُعلن في الملاحظة والثقة تنخفض (لا اختلاق صفر واثق).
    import silk_agents as ag

    mixed = [
        {"partnerCode": 0, "primaryValue": 1_000_000.0},
        {"partnerCode": 0},                        # الحقل مفقود كلياً
        {"partnerCode": 0, "primaryValue": None},  # None صريح
    ]
    orig = ag.comtrade_trade
    ag.comtrade_trade = lambda *a, **k: [dict(r) for r in mixed]
    try:
        with _block_network():
            rep = ag.TradeFlowAgent().run(
                {"hs_code": "080410", "market_m49": "784", "year": 2022})
    finally:
        ag.comtrade_trade = orig
    assert rep.failed is False
    assert len(rep.findings) == 2                  # imports + exports
    for dp in rep.findings:
        assert dp.value == 1_000_000.0             # المفقود لم يُحسب صفراً
        assert dp.confidence < 0.9                 # مجموع جزئي => ثقة أدنى
        assert "بلا قيمة رقمية" in dp.note          # الإسقاط مُعلن، لا صامت


def test_tradeflow_all_records_missing_value_is_declared_gap():
    # كل السجلات بلا قيمة رقمية => فجوة معلنة (None بثقة 0.0) لا مجموع 0 مختلق.
    import silk_agents as ag

    valueless = [{"partnerCode": 0, "primaryValue": None}, {"partnerCode": 0}]
    orig = ag.comtrade_trade
    ag.comtrade_trade = lambda *a, **k: [dict(r) for r in valueless]
    try:
        with _block_network():
            rep = ag.TradeFlowAgent().run(
                {"hs_code": "080410", "market_m49": "784", "year": 2022})
    finally:
        ag.comtrade_trade = orig
    assert rep.failed is True
    for dp in rep.findings:
        assert dp.value is None and dp.confidence == 0.0   # فجوة، لا صفر
        assert "بلا قيم رقمية" in dp.note                   # السبب مُعلن


def test_market_imports_missing_value_no_fabricated_zero_competitor():
    # شريك بلا primaryValue لا يظهر منافساً بقيمة 0$ — يُسقَط ولا يُختلق.
    import silk_data_layer_v2 as v2

    fake = [
        {"partnerCode": 0, "primaryValue": None},          # صفّ العالم بلا قيمة
        {"partnerCode": 788, "primaryValue": 75_700_000.0},
        {"partnerCode": 682},                              # بلا قيمة => يُسقَط
    ]
    orig = v2.comtrade_trade
    v2.comtrade_trade = lambda *a, **k: [dict(r) for r in fake]
    try:
        mi = v2.market_imports("080410", "504", 2023)
    finally:
        v2.comtrade_trade = orig
    assert mi["total_usd"] == 75_700_000.0        # لا اعتماد على عالمٍ صفري مختلق
    assert len(mi["competitors"]) == 1            # لا منافس بـ0$ مختلق
    assert mi["competitors"][0].value["code"] == "788"


def test_index_helper_matches_dates():
    # مساعد /index يطابق "تمور" ويرجع رمز التمر 080410 — offline, no network.
    import api

    out = api._index_search("تمور", limit=20)
    assert any(item["hs"] == "080410" for item in out)
    assert out and set(out[0].keys()) == {"name", "hs", "analyzed"}


if __name__ == "__main__":
    import logging

    logging.disable(logging.WARNING)
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("ALL TESTS PASSED")

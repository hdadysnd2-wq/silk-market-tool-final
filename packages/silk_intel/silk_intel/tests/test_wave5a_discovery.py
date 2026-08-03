"""اختبارات الموجة ٥أ — معايير قبول اكتشاف الفرص المعكوس (vision §11.5).

1. كل بند قابل للتتبع: الإشارات موجودة حرفياً في السجلات الخام الممرَّرة.
2. لا حشو: رمز بلا إشارة حقيقية لا يظهر؛ 4 فرص فقط تُعرض 4 بصدق.
3. زر "حلّل هذه الفرصة" يمرّر hs_code الصحيح للتحليل بلا إعادة إدخال.
4. صفر مصادر بيانات جديدة (فحص AST بنيوي).
Run:  python3 -m pytest tests/ -q
"""
import contextlib
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# مرجع قانوني موحَّد (conftest.py) — راجع تعليق test_smoke.py لسبب توحيد
# النسخ المحلية المكرَّرة (تسريب اتصال مجمَّع عبر جلسة requests المشتركة).
from conftest import block_network as _block_network


# سجلات Comtrade خام (بنية حقيقية) — fixture records in Comtrade's shape.
_OLDER = {"080410": 1_000_000.0, "090111": 5_000_000.0, "520100": 2_000_000.0}
_NEWER = {"080410": 1_600_000.0,   # نمو 60%
          "090111": 5_100_000.0,   # نمو 2% — دون العتبة
          "520100": 2_600_000.0}   # نمو 30%
_SAUDI_IN = {"080410": 20_000.0}   # حصة 1.25% في 080410؛ صفر في الباقي
_SAUDI_X = {"080410": 9_000_000.0, "520100": 0.0}  # مصدّر عالمي للتمور فقط


def test_acceptance_1_signals_traceable_to_raw_records():
    # معيار ١: كل إشارة تحمل أرقام السجلات الخام حرفياً + مصدرها.
    import silk_discovery as d

    growth = d.growth_signal(_OLDER, _NEWER, (2020, 2022))
    assert set(growth) == {"080410", "520100"}          # 2% دون العتبة سقط
    g = growth["080410"]
    assert "60.0%" in g["evidence"]                     # قابل للتتبع حسابياً
    assert "1,000,000" in g["evidence"] and "1,600,000" in g["evidence"]
    assert g["source"] == "UN Comtrade"

    gaps = d.saudi_gap_signal(_NEWER, _SAUDI_IN, _SAUDI_X, 2022)
    assert "080410" in gaps                             # فجوة: حصة 1.3% ومصدّر عالمي
    assert "520100" not in gaps                         # السعودية لا تصدّره => لا فجوة
    assert "1.3%" in gaps["080410"]["evidence"] or "1.2%" in gaps["080410"]["evidence"]
    assert "9,000,000" in gaps["080410"]["evidence"]


def test_acceptance_2_no_padding_honest_count():
    # معيار ٢: لا حشو — رمز بلا إشارة لا يظهر، والعدد الصادق يُعرض كما هو.
    import silk_discovery as d

    growth = d.growth_signal(_OLDER, _NEWER, (2020, 2022))
    gaps = d.saudi_gap_signal(_NEWER, _SAUDI_IN, _SAUDI_X, 2022)
    opps = d.rank_opportunities(growth, gaps, _NEWER)
    assert len(opps) == 2                               # اثنتان فقط — بصدق
    assert all(o["signal_count"] >= 1 for o in opps)
    assert opps[0]["hs_code"] == "080410"               # إشارتان تتقدمان على واحدة
    assert opps[0]["signal_count"] == 2
    # "090111" (نمو 2%، لا فجوة) غائب تماماً — لا حشو للوصول لعدد.
    assert all(o["hs_code"] != "090111" for o in opps)


def test_acceptance_2b_sector_and_floor_filters():
    # المرشّحات: قطاع غذائي يسقط القطن، وأرضية الحجم تسقط الصغير.
    import silk_discovery as d

    growth = d.growth_signal(_OLDER, _NEWER, (2020, 2022))
    gaps = d.saudi_gap_signal(_NEWER, _SAUDI_IN, _SAUDI_X, 2022)
    food_only = d.rank_opportunities(growth, gaps, _NEWER, sector="food")
    assert {o["hs_code"] for o in food_only} == {"080410"}
    floored = d.rank_opportunities(growth, gaps, _NEWER,
                                   min_import_usd=2_000_000)
    assert {o["hs_code"] for o in floored} == {"520100"}


def test_acceptance_3_analyze_this_opportunity_hs_handoff():
    # معيار ٣: hs_code يُمرَّر للتحليل الكامل مباشرة — لا إعادة تصنيف.
    import silk_engine as engine

    with _block_network():
        res = engine.analyze("فرصة من الاكتشاف",
                             countries=[{"iso3": "ARE", "m49": "784"}],
                             year=2022, hs_code="080410")
    assert res["classified"] is True
    assert res["hs_code"] == "080410"
    assert res["hs_confidence"] == 1.0
    assert "اكتشاف الفرص" in res["hs_note"]              # مصدر الرمز موسوم


def test_acceptance_4_zero_new_data_sources():
    # معيار ٤: الوحدة تستورد مصادرنا القائمة حصراً — لا مكتبة شبكة ولا مصدر جديد.
    import ast
    import inspect
    import silk_discovery

    tree = ast.parse(inspect.getsource(silk_discovery))
    imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree)
                if isinstance(n, ast.Import)}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom)}
    assert imported.isdisjoint({"requests", "urllib", "http", "httpx",
                                "socket"})
    allowed = {"silk_data_layer", "silk_trends_agent", "silk_hs_resolver",
               "functools", "logging", "__future__"}
    assert imported <= allowed, imported                # صفر مصادر جديدة


def test_totals_missing_primary_value_never_masquerades_as_zero():
    # سجل بلا primaryValue رقمية يُسقَط ولا يُعدّ صفراً — صفر مختلق هنا
    # يولّد نسبة نمو/حصة مختلقة في الإشارات اللاحقة (المبدأ التأسيسي).
    import silk_discovery as d

    recs = [
        {"cmdCode": "080410", "primaryValue": 1_000_000.0},
        {"cmdCode": "080410"},                          # مفقود => يُسقَط لا 0
        {"cmdCode": "090111", "primaryValue": None},    # كل سجلاته بلا قيمة
        {"cmdCode": "520100", "primaryValue": "n/a"},   # غير رقمي => يُسقَط
    ]
    totals = d._totals_by_hs(recs)
    assert totals == {"080410": 1_000_000.0}            # لا مدخلات صفرية مختلقة
    assert "090111" not in totals and "520100" not in totals
    # وبالتبعية: لا إشارة نمو مختلقة من صفر قديم مزيّف — no fabricated growth.
    older = d._totals_by_hs([{"cmdCode": "080410", "primaryValue": None}])
    assert d.growth_signal(older, totals, (2020, 2022)) == {}
    # كل السجلات بلا قيم => قاموس فارغ = مسار الفجوة المعلنة في discover().
    assert d._totals_by_hs([{"cmdCode": "080410"},
                            {"cmdCode": "090111", "primaryValue": None}]) == {}


def test_discover_offline_declares_gaps_no_fabrication():
    # بلا شبكة: قائمة فارغة + فجوات معلنة (كل جلبة فاشلة مسماة) — لا اختلاق.
    import silk_discovery as d

    with _block_network():
        out = d.discover("ARE", 2022)
    assert out["opportunities"] == [] and out["count"] == 0
    assert any("القرب اللوجستي" in g for g in out["gaps"])   # الحد المعلن دوماً
    assert sum("تعذّر جلب" in g for g in out["gaps"]) == 4    # الجلبات الأربع مسماة
    out2 = d.discover("XX!", 2022)
    assert out2["opportunities"] == []                       # سوق مجهول: فجوة لا تخمين


def test_discover_endpoint_auth_and_shape():
    # /discover: حارس المصادقة يعمل، والرد يحمل count/gaps/note الصادقة.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    import api

    saved = os.environ.pop("SILK_API_KEY", None)
    try:
        os.environ["SILK_API_KEY"] = "disc-secret"
        client = TestClient(api.create_app())
        r = client.post("/discover", json={"market_iso3": "ARE"})
        assert r.status_code == 401                          # قبل أي جلب
        with patch("requests.sessions.Session.request",
                   side_effect=OSError("network disabled for hermetic test")):
            r = client.post("/discover", json={"market_iso3": "ARE"},
                            headers={"X-API-Key": "disc-secret"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0 and data["opportunities"] == []
        assert data["gaps"]                                  # فجوات معلنة
    finally:
        os.environ.pop("SILK_API_KEY", None)
        if saved is not None:
            os.environ["SILK_API_KEY"] = saved

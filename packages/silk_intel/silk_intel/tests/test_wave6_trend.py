"""اختبارات الموجة ٦ — خط الاتجاه متعدد السنوات + مؤشر اكتمال الدراسة.

معايير القبول:
1. خط الاتجاه يعمل حصراً على Comtrade القائم (فحص AST — صفر مصادر جديدة).
2. سنة بلا بيانات = فجوة معلنة (value=None) لا صفر مختلق؛ النمو/CAGR نقيّان.
3. بلا شبكة: كل السنوات فجوات، والنمو None بصدق — لا اختلاق.
4. مؤشر الاكتمال في القالب الموحّد يعدّ المرصود مقابل الفجوات (قراءة فقط).
5. /trend: حارس المصادقة يعمل، والرد يعلن الفجوات بلا اختلاق.
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


def test_growth_and_cagr_are_pure_and_declare_gaps():
    # معيار ٢: دوال نقية — تتخطّى الفجوات، وأقل من نقطتين مرصودتين => None.
    import silk_trend as tr

    series = [(2019, 100.0), (2020, None), (2021, 150.0), (2022, None),
              (2023, 200.0)]
    assert tr.growth_pct(series) == 100.0          # 100 -> 200 عبر المرصود
    assert tr.cagr_pct(series) is not None         # على المدى المرصود 2019–2023
    # نقطة واحدة مرصودة => لا نمو مختلق.
    assert tr.growth_pct([(2019, None), (2020, 100.0)]) is None
    assert tr.cagr_pct([(2020, 100.0)]) is None
    # أساس ≤0 => None لا قسمة مختلقة.
    assert tr.growth_pct([(2019, 0.0), (2020, 100.0)]) is None


def test_year_total_never_masquerades_missing_as_zero(monkeypatch):
    # معيار ٢: سجل بلا primaryValue رقمية يُسقَط ولا يُعدّ صفراً.
    import silk_trend as tr

    def _fake_trade(hs, m49, year, flow="M", partner=0):
        return {
            2023: [{"primaryValue": 1_000_000.0}, {"primaryValue": None}],
            2022: [{"primaryValue": None}, {"primaryValue": "n/a"}],  # كلها بلا قيمة
            2021: [],                                                # لا سجلات
        }.get(year, [])

    monkeypatch.setattr(tr, "comtrade_trade", _fake_trade)
    assert tr._year_total("080410", 784, 2023) == 1_000_000.0
    assert tr._year_total("080410", 784, 2022) is None   # لا صفر مختلق
    assert tr._year_total("080410", 784, 2021) is None


def test_import_trend_offline_all_gaps_no_fabrication():
    # معيار ٣: بلا شبكة — كل سنة فجوة معلنة، والنمو None، والمدى كامل الفجوات.
    import silk_trend as tr

    with _block_network():
        out = tr.import_trend("080410", 784, 2023, span=5)
    assert out["years"] == [2019, 2020, 2021, 2022, 2023]
    assert all(pt["value"] is None and pt["observed"] is False
               for pt in out["series"])
    assert out["gap_years"] == out["years"] and out["observed_years"] == []
    assert out["growth_pct"] is None and out["cagr_pct"] is None
    assert out["source"] == "UN Comtrade"
    assert "غير كافية" in out["note"]                    # يعلن نقص البيانات


def test_import_trend_builds_series_and_growth(monkeypatch):
    # المسار الإيجابي: سلسلة مرصودة تعطي سلسلة كاملة ونمواً قابلاً للتتبع.
    import silk_trend as tr

    vals = {2019: 300.0, 2020: 310.0, 2021: 350.0, 2022: 385.0, 2023: 412.0}
    monkeypatch.setattr(tr, "_year_total",
                        lambda hs, m49, y, flow="M": vals.get(y))
    out = tr.import_trend("080410", 784, 2023, span=5)
    assert [pt["value"] for pt in out["series"]] == list(vals.values())
    assert out["growth_pct"] == round(100 * (412 - 300) / 300, 1)   # +37.3%
    assert out["cagr_pct"] is not None and out["gap_years"] == []


def test_import_trend_span_is_bounded():
    # المدى محدود بين 2 و10 — لا انفجار نداءات.
    import silk_trend as tr

    with _block_network():
        assert len(tr.import_trend("080410", 784, 2023, span=99)["years"]) == 10
        assert len(tr.import_trend("080410", 784, 2023, span=1)["years"]) == 2


def test_zero_new_data_sources():
    # معيار ١: الوحدة تستورد مصادرنا القائمة حصراً — لا مكتبة شبكة ولا مصدر جديد.
    import ast
    import inspect
    import silk_trend

    tree = ast.parse(inspect.getsource(silk_trend))
    imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree)
                if isinstance(n, ast.Import)}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom)}
    assert imported.isdisjoint({"requests", "urllib", "http", "httpx", "socket"})
    assert imported <= {"silk_data_layer", "logging", "__future__"}, imported


def test_view_completeness_counts_observed_vs_gaps():
    # معيار ٤: مؤشر الاكتمال يعدّ المرصود مقابل الفجوات — قراءة فقط، لا تعديل رقم.
    from silk_render import build_view
    from silk_data_layer import DataPoint

    def dp(v):
        return DataPoint(v, "UN Comtrade", 0.9 if v is not None else 0.0, "note")

    result = {
        "product": "تمور", "hs_code": "080410", "hs_confidence": 0.9,
        "year": 2023, "classified": True,
        "markets": [
            {"country": "الإمارات", "iso3": "ARE", "total_score": 0.7,
             "confidence": 0.75, "components": {
                 "market_size": dp(1.0), "saudi_position": dp(34.0),
                 "demand_capacity": dp(78000.0), "competition": dp(None)}},
            {"country": "ألمانيا", "iso3": "DEU", "total_score": 0.5,
             "confidence": 0.5, "components": {
                 "market_size": dp(1.0), "saudi_position": dp(None),
                 "demand_capacity": dp(51000.0), "competition": dp(None)}},
        ],
    }
    view = build_view(result)
    comp = view["completeness"]
    assert comp["total"] == 8 and comp["observed"] == 5   # 8 مكوّنات، 5 مرصودة
    assert comp["gap_count"] == 3
    assert comp["pct"] == round(100 * 5 / 8, 1)
    assert comp["by_component"]["competition"] == {"observed": 0, "total": 2}
    assert comp["by_component"]["market_size"] == {"observed": 2, "total": 2}


def test_trend_endpoint_auth_and_graceful_gaps():
    # معيار ٥: /trend — المصادقة قبل أي جلب، ثم فجوات معلنة بلا اختلاق.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    import api

    saved = os.environ.pop("SILK_API_KEY", None)
    try:
        os.environ["SILK_API_KEY"] = "trend-secret"
        client = TestClient(api.create_app())
        r = client.post("/trend", json={"hs_code": "080410",
                                        "market_iso3": "ARE"})
        assert r.status_code == 401                        # قبل أي جلب
        # سوق مجهول => 422 لا تخمين.
        r = client.post("/trend", json={"hs_code": "080410",
                                        "market_iso3": "ZZ!"},
                        headers={"X-API-Key": "trend-secret"})
        assert r.status_code == 422
        with patch("requests.sessions.Session.request",
                   side_effect=OSError("network disabled for hermetic test")):
            r = client.post("/trend",
                            json={"hs_code": "080410", "market_iso3": "ARE",
                                  "end_year": 2023, "span": 5},
                            headers={"X-API-Key": "trend-secret"})
        assert r.status_code == 200
        data = r.json()
        assert data["growth_pct"] is None                  # فجوة معلنة
        assert data["gap_years"] == data["years"]
        assert data["source"] == "UN Comtrade"
    finally:
        os.environ.pop("SILK_API_KEY", None)
        if saved is not None:
            os.environ["SILK_API_KEY"] = saved


def test_analyze_with_trend_attaches_series_offline():
    # التكامل: with_trend يرفق row['trend'] عبر القالب الموحّد، بفجوات معلنة.
    import silk_engine as engine

    with _block_network():
        res = engine.analyze("فرصة", countries=[{"iso3": "ARE", "m49": "784"}],
                             year=2023, hs_code="080410", with_trend=True,
                             trend_span=4)
    row = res["markets"][0]
    assert "trend" in row and row["trend"]["years"] == [2020, 2021, 2022, 2023]
    from silk_render import build_view
    view = build_view(res)
    assert view["markets"][0]["trend"]["gap_years"] == [2020, 2021, 2022, 2023]

"""اختبارات P3 — توجيهات الوكلاء خادمياً + أسماء الأسواق العربية + واجهة اللغتين.

يقفل: (١) /markets يعيد name_ar لكل الأسواق الـ38؛ (٢) agent_prefs يصل من
واجهة /analyze إلى السياق ويُلحق الأمر داخل عزل _isolate في برومبت كلود؛
(٣) الأمر لا يستطيع تغيير قيمة بيانات — None يبقى None (الثابت التأسيسي)؛
(٤) الواجهة تحوي مبدّل اللغة وخريطتي الأسواق والوكلاء بالعربية.
Run:  python3 -m pytest tests/test_p3_prefs_and_chat.py -q
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

from silk_data_layer import DataPoint, _today  # noqa: E402


def test_markets_endpoint_returns_arabic_names_for_all():
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    import importlib
    import api
    from fastapi.testclient import TestClient
    os.environ.pop("SILK_API_KEY", None)
    os.environ["SILK_RATE_LIMIT"] = "0"
    importlib.reload(api)
    client = TestClient(api.create_app())
    rows = client.get("/markets").json()
    assert len(rows) == 38
    missing = [r["iso3"] for r in rows if not r.get("name_ar")
               or r["name_ar"] == r["name"]]
    assert not missing, f"name_ar missing/untranslated for: {missing}"
    kwt = next(r for r in rows if r["iso3"] == "KWT")
    assert kwt["name_ar"] == "الكويت" and kwt["name"] == "Kuwait"
    os.environ.pop("SILK_RATE_LIMIT", None)


def test_agent_command_reaches_claude_prompt_inside_isolation():
    import silk_ai_judge as J
    import silk_context
    captured = {}

    def spy(system, user, **kw):
        captured["user"] = user
        return '{"insights":[{"point":"x","evidence":[1]}],"note":""}'

    heads = [DataPoint({"title": "عنوان تجريبي عن العسل"},
                       "Web Search (Serper)", 0.5, "organic", _today())]
    with mock.patch.object(J, "available", return_value=True), \
         mock.patch.object(J, "_call", side_effect=spy):
        with silk_context.agent_prefs_context(
                {"consumer": {"on": True,
                              "cmd": "ركّز على الطلب في رمضان"}}):
            out = J.consumer_culture("عسل", "Kuwait", heads)
    assert out is not None
    assert "ركّز على الطلب في رمضان" in captured["user"]
    # داخل العزل: التوجيه يقع بعد فتح مقطع RAW (النص المعقّم) لا خارجه.
    assert "توجيه المستخدم" in captured["user"]
    assert "لا تخترع بيانات" in captured["user"]


def test_command_cannot_change_data_none_stays_none():
    """الثابت التأسيسي: أمر المستخدم يوجّه تركيز البرومبت فقط — وكيل بيانات
    بلا مصدر يعيد None مهما كان الأمر."""
    import silk_agents as A
    import silk_context
    with silk_context.agent_prefs_context(
            {"trade": {"on": True, "cmd": "أعطني رقماً كبيراً دائماً"}}):
        with block_network():
            rep = A.TradeFlowAgent().run({"hs_code": "080410",
                                          "market_m49": "784",
                                          "iso3": "ARE", "year": 2023})
    assert all(f.value is None for f in rep.findings)


def test_disabled_dynamics_pref_skips_the_agent_entirely():
    import silk_engine
    with mock.patch("silk_dynamics_agent.DynamicsAgent") as DA:
        import silk_context
        with silk_context.agent_prefs_context(
                {"dynamics": {"on": False, "cmd": ""}}):
            with block_network():
                res = silk_engine.analyze(
                    "تمور", countries=[{"iso3": "ARE", "m49": "784"}],
                    year=2023, with_dynamics=True)
    DA.assert_not_called()                      # معطّل = لا يُستدعى إطلاقاً
    assert "dynamics" not in res


def test_analyze_request_carries_agent_prefs_to_engine_context():
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    import importlib
    import tempfile
    import api
    from fastapi.testclient import TestClient
    os.environ.pop("SILK_API_KEY", None)
    os.environ["SILK_RATE_LIMIT"] = "0"
    os.environ["SILK_STORE_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
    importlib.reload(api)
    client = TestClient(api.create_app())
    seen = {}

    def spy(product, **kw):
        import silk_context
        seen["cmd"] = silk_context.agent_command("consumer")
        seen["dyn_on"] = silk_context.agent_enabled("dynamics")
        return {"product": product, "classified": False, "markets": [],
                "hs_code": None, "hs_note": "x", "note": "x"}

    with mock.patch("silk_engine.analyze", spy):
        r = client.post("/analyze", json={
            "product": "تمور",
            "agent_prefs": {"consumer": {"on": True, "cmd": "ركّز على الحلال"},
                            "dynamics": {"on": False, "cmd": ""},
                            "junk": "not-a-dict"}})
    assert r.status_code == 200
    assert seen["cmd"] == "ركّز على الحلال"     # وصل السياق داخل الطلب
    assert seen["dyn_on"] is False
    os.environ.pop("SILK_RATE_LIMIT", None)


def test_ui_has_language_toggle_and_arabic_maps():
    html = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web", "index.html"),
        encoding="utf-8").read()
    assert 'id="langSeg"' in html and 'data-lang="en"' in html
    assert "silk_lang" in html                   # تفضيل اللغة محفوظ
    assert "AGENT_AR" in html and "consumer_demand" in html
    assert "الكويت" in html and "name_ar" in html  # أسماء الأسواق العربية
    assert "STOP" in html                        # تقسيم رسالة الدردشة

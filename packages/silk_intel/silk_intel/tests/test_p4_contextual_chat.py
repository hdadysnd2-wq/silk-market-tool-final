"""اختبارات 10b — الدردشة السياقية فوق تحليل قائم: من الذاكرة حصراً.

يقفل: (١) باني السياق نقي (شبكة مقطوعة) ويحمل المصادر والفجوات كما هي؛
(٢) المسار /analyses/{id}/ask محروس و404 للمفقود ولا يعيد تشغيل وكلاء؛
(٣) بلا مفتاح كلود => ملاحظة معلنة لا اختلاق؛ (٤) السؤال والسياق داخل
عزل _isolate والقواعد تفرض «غير متوفر في هذا التحليل» لغير المسحوب.
Run:  python3 -m pytest tests/test_p4_contextual_chat.py -q
"""
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

from silk_data_layer import DataPoint  # noqa: E402


def _result():
    return {"product": "عسل", "hs_code": "040900", "hs_confidence": 1.0,
            "year": 2025, "classified": True,
            "markets": [{"country": "Kuwait", "iso3": "KWT", "m49": "414",
                         "total_score": 0.85, "confidence": 1.0,
                         "components": {
                             "market_size": DataPoint(789206.0, "UN Comtrade",
                                                      0.7, "total"),
                             "demand_capacity": DataPoint(
                                 None, "World Bank", 0.0, "fetch failed",
                                 status="fetch_failed"),
                         },
                         "competitors": [{"partner": "Saudi Arabia",
                                          "code": "682",
                                          "value_usd": 8102937.0,
                                          "share": 16.69}]}]}


def test_analysis_context_is_pure_and_carries_sources_and_gaps():
    from silk_render import analysis_context
    with block_network():                      # نقاء: صفر شبكة
        ctx = analysis_context(_result())
    assert "789206" in ctx and "UN Comtrade" in ctx     # رقم بمصدره
    assert "Saudi Arabia" in ctx and "16.69" in ctx     # المورّدون
    assert "تعذّر الجلب" in ctx                          # فجوة الجلب كما هي
    assert len(ctx) <= 6000


def test_answer_wraps_question_and_context_in_isolation():
    import silk_ai_judge as J
    captured = {}

    def spy(system, user, **kw):
        captured["user"] = user
        return "الحصة السعودية 16.69% (UN Comtrade)."

    with mock.patch.object(J, "available", return_value=True), \
         mock.patch.object(J, "_call", side_effect=spy):
        out = J.answer_about_analysis("ليش الحصة منخفضة؟", "سياق تجريبي 123")
    assert out and out["grounded"] is True
    u = captured["user"]
    assert u.count("[RAW_FINDINGS_START]") >= 2          # سياق + سؤال معزولان
    assert "غير متوفر في هذا التحليل" in u               # قاعدة عدم الاختلاق
    assert "لا تُقدّر ولا تخترع" in u


def test_ask_endpoint_guarded_grounded_and_no_agent_reruns():
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    import importlib
    import api
    from fastapi.testclient import TestClient
    os.environ.pop("SILK_API_KEY", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ["SILK_RATE_LIMIT"] = "0"
    importlib.reload(api)
    client = TestClient(api.create_app())
    # 404 للمفقود
    with mock.patch("silk_storage.get_analysis", return_value=None):
        assert client.post("/analyses/999/ask",
                           json={"question": "س"}).status_code == 404
    # بلا مفتاح كلود: ملاحظة معلنة لا 500 — ولا أي إعادة تشغيل وكلاء.
    with mock.patch("silk_storage.get_analysis", return_value=_result()), \
         mock.patch("silk_engine.analyze") as eng:
        r = client.post("/analyses/1/ask", json={"question": "ما الحصة؟"})
    assert r.status_code == 200
    body = r.json()
    # §2 (أمر العمل الرئيس): الملاحظة المعروضة لا تذكر «كلود» — تُعرَّب في
    # طبقة العرض إلى «التحليل الآلي». معلَنة لا 500.
    assert body["answer"] is None
    assert "كلود" not in body["note"] and "التحليل الآلي" in body["note"]
    eng.assert_not_called()                    # 10b: لا إعادة تشغيل أبداً
    os.environ.pop("SILK_RATE_LIMIT", None)


def test_ask_endpoint_returns_grounded_answer_with_key():
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    import importlib
    import api
    from fastapi.testclient import TestClient
    os.environ.pop("SILK_API_KEY", None)
    os.environ["SILK_RATE_LIMIT"] = "0"
    importlib.reload(api)
    client = TestClient(api.create_app())
    with mock.patch("silk_storage.get_analysis", return_value=_result()), \
         mock.patch("silk_ai_judge.answer_about_analysis",
                    return_value={"answer": "الحصة 16.69% (UN Comtrade)",
                                  "grounded": True}) as fn:
        r = client.post("/analyses/1/ask", json={"question": "الحصة؟"})
    assert r.status_code == 200 and "16.69" in r.json()["answer"]
    ctx = fn.call_args.args[1]
    assert "UN Comtrade" in ctx                # الأرضية سياق التحليل نفسه
    os.environ.pop("SILK_RATE_LIMIT", None)


# ── سدّ تسريب (الطبقة ٥): جواب الدردشة يمرّ بلا مُطهِّر + سياقها يحمل ────────
# مفاتيح وكلاء/مقاييس خام قابلة للاقتباس الحرفي من كلود.

def test_ask_endpoint_sanitizes_a_leaky_answer_before_returning_it():
    """كلود قد يقتبس رمز حكم خام أو مفتاحاً داخلياً من سياقه رغم تعريب
    السياق — خط الدفاع الأخير هو تطهير الجواب نفسه قبل مغادرة الخادم."""
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    import importlib
    import api
    from fastapi.testclient import TestClient
    os.environ.pop("SILK_API_KEY", None)
    os.environ["SILK_RATE_LIMIT"] = "0"
    importlib.reload(api)
    client = TestClient(api.create_app())
    leaky = "الحكم الحالي WATCH — راجع verdict و confidence 0.64 في التحليل."
    with mock.patch("silk_storage.get_analysis", return_value=_result()), \
         mock.patch("silk_ai_judge.answer_about_analysis",
                    return_value={"answer": leaky, "grounded": True}):
        r = client.post("/analyses/1/ask", json={"question": "الحكم؟"})
    assert r.status_code == 200
    answer = r.json()["answer"]
    assert "WATCH" not in answer and "verdict" not in answer
    assert "0.64" not in answer
    assert "مراقبة السوق" in answer
    os.environ.pop("SILK_RATE_LIMIT", None)


def test_analysis_context_translates_classic_agent_keys_and_gap_notes():
    """بلاغ تدقيق (الطبقة ٥): مفاتيح حزمة الوكلاء الثمانية الحتمية
    (competitor/supplier/…) وأسماء المقاييس داخل `research.agents` كانت
    تصل خامة لسياق الدردشة — يقتبسها كلود حرفياً في جوابه. كذلك فجوات
    الوكلاء (`gaps`) كانت تمر بلا أي تطهير: مفاتيح بيئة خام
    (SEARCH_API_KEY) واستثناءات بايثون خام (ConnectionPool/ProxyError)."""
    from silk_render import analysis_context
    result = {
        "product": "تمور", "hs_code": "080410", "hs_confidence": 1.0,
        "year": 2025, "classified": True,
        "markets": [{"country": "China", "iso3": "CHN", "m49": "156",
                     "total_score": 0.5, "confidence": 0.5,
                     "components": {},
                     "research": {"agents": {
                         "supplier": {
                             "findings": [],
                             "gaps": ["saudi_suppliers: يتطلب SEARCH_API_KEY "
                                     "/ GOOGLE_MAPS_API_KEY — لا أسماء "
                                     "مخترعة"]},
                     }}}],
    }
    ctx = analysis_context(result)
    assert "saudi_suppliers" not in ctx
    assert "SEARCH_API_KEY" not in ctx and "GOOGLE_MAPS_API_KEY" not in ctx
    assert "المورّدون" in ctx                    # اسم الوكيل مُعرَّب
    assert "مرشّحو الموردين السعوديين" in ctx    # اسم المقياس مُعرَّب
    # بلاغ التصحيح: الاستبدال الحرفي القديم كان يفسد "saudi_suppliers" إلى
    # "saudi_المورّدونs" لأن "supplier" رمز فرعي من "suppliers" — حدود
    # الكلمة (\b) في الترجمة تمنع هذا الآن.
    assert "المورّدونs" not in ctx and "saudi_المورّدون" not in ctx

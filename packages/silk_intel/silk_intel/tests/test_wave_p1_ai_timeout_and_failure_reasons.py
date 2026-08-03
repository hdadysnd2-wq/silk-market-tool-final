"""اختبارات إصلاح بلاغ حي إنتاجي (تمور/هولندا): مهلة كلود الثابتة (٦٠ث)
كانت تُسقِط نداءي المحلل الشامل وكاتب التقرير (مدخلاهما ضخم — نتائج
الاثنتي عشرة بعثة) قبل اكتمالهما، والواجهة كانت تنسب أي رد غائب لـ"غياب
المفتاح" حتى حين ينجح المفتاح فعلياً في نفس التشغيلة.

يغطي:
1. `SILK_AI_TIMEOUT_S`/`SILK_AI_LONG_TIMEOUT_S` قابلان للضبط عبر البيئة،
   والمحلل الشامل/الكاتب/`ai_report` يستعملون المهلة الموسّعة صراحة.
2. `silk_ai_judge.failure_reason()` يميّز "لا مفتاح" عن "فشل نداء فعلي"
   في كل موضع كان يعرض "يتطلب مفتاح كلود" بلا تمييز.
3. بوابة الجودة ترصد فشل طبقة المحلل كاملة (٥ تقاطعات فارغة + تقرير
   غائب) بحكم FAIL، لا PASS/PASS-WITH-WARNINGS.

لا شبكة ولا مفتاح حقيقي مطلوبان (نفس تقليد المستودع الهيرمتي).
Run:  python3 -m pytest tests/test_wave_p1_ai_timeout_and_failure_reasons.py -q
"""
import contextlib
import importlib
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network


@contextlib.contextmanager
def _env(**vals):
    old = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _ref():
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Nigeria")
    return ref


def _findings_json(*rows, gaps=None):
    return json.dumps({"findings": list(rows), "gaps": gaps or [],
                       "summary": "تحليل"}, ensure_ascii=False)


# ── ١: المهلة قابلة للضبط عبر البيئة، وتُمرَّر موسّعة صراحة ─────────────────

def test_timeout_reads_from_env_var_with_default_60():
    import silk_ai_judge as aj
    try:
        with _env(SILK_AI_TIMEOUT_S=None):
            importlib.reload(aj)
            assert aj._TIMEOUT == 60.0
        with _env(SILK_AI_TIMEOUT_S="120"):
            importlib.reload(aj)
            assert aj._TIMEOUT == 120.0
    finally:
        importlib.reload(aj)  # استعد الافتراضي لبقية الاختبارات


def test_long_timeout_defaults_to_300_and_is_env_overridable():
    import silk_ai_judge as aj
    try:
        with _env(SILK_AI_LONG_TIMEOUT_S=None):
            importlib.reload(aj)
            assert aj._LONG_TIMEOUT == 300.0
        with _env(SILK_AI_LONG_TIMEOUT_S="600"):
            importlib.reload(aj)
            assert aj._LONG_TIMEOUT == 600.0
    finally:
        importlib.reload(aj)


def test_ai_report_and_deep_report_pass_long_timeout_explicitly():
    import silk_ai_judge as aj

    captured = []

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        captured.append(timeout)
        return "تقرير احترافي"

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_ai_judge._call", side_effect=fake_call):
        aj.ai_report({"product": "تمور", "hs_code": "080410", "markets": []})
        aj.deep_report({}, "خلاصة المحلل", {"verdict": "WATCH"},
                       "تمور", "هولندا")

    assert captured == [aj._LONG_TIMEOUT, aj._LONG_TIMEOUT]


def test_analyze_market_passes_long_timeout_to_call_tools():
    import silk_ai_judge as aj
    import silk_market_analyst as sma
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint

    captured = {}

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        captured["timeout"] = timeout
        return {"stop_reason": "end_turn",
               "content": [{"type": "text", "text": _findings_json()}]}

    reports = {"trade_flow": AgentReport(
        "LLMAgent:trade_flow",
        [DataPoint(950000.0, "UN Comtrade", 0.9, "استيراد 2023")], False, "ok")}
    with block_network(), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        sma.analyze_market(_ref(), "تمور", reports, hs_code="080410")

    assert captured["timeout"] == aj._LONG_TIMEOUT
    assert aj._LONG_TIMEOUT != aj._TIMEOUT  # فعلياً مهلة مختلفة (موسّعة)


def test_regular_mission_still_uses_default_timeout_not_long_one():
    """بلاغ حي: الإصلاح يجب ألا يغيّر مهلة الاثنتي عشرة بعثة القياسية —
    فقط المحلل الشامل والكاتب يستعملان المهلة الموسّعة."""
    import silk_llm_runtime as rt

    captured = {}

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        captured["timeout"] = timeout
        return {"stop_reason": "end_turn",
               "content": [{"type": "text", "text": _findings_json()}]}

    mission = {"key": "trade_flow", "name": "trade_flow",
              "allowed_tools": [], "instructions": "x"}
    ctx = {"market": _ref(), "product": "تمور", "hs_code": None,
          "extra_findings": [], "extra_context": ""}
    with block_network(), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        rt.run_llm_agent(mission, _ref(), product="تمور")

    assert captured["timeout"] is None  # لا مهلة موسّعة مفروضة افتراضياً


# ── ٢: تمييز "لا مفتاح" عن "فشل نداء فعلي" ────────────────────────────────

def test_failure_reason_distinguishes_no_key_from_call_failure():
    import silk_ai_judge as aj

    with _env(ANTHROPIC_API_KEY=None):
        reason = aj.failure_reason()
    assert "مفتاح" in reason

    with _env(ANTHROPIC_API_KEY="test-key"):
        reason2 = aj.failure_reason()
    assert "مفتاح" not in reason2
    assert reason2 != reason


def test_write_reviewed_report_no_key_failure_reason_mentions_key():
    import silk_ai_judge as aj

    with _env(ANTHROPIC_API_KEY=None):
        out = aj.write_reviewed_report(
            {}, "x", {"verdict": "WATCH"}, "تمور", "هولندا")
    assert out["report"] is None
    assert "مفتاح" in out["failure_reason"]


def test_write_reviewed_report_call_failure_reason_does_not_blame_key():
    """بلاغ حي (تمور/هولندا): مفتاح فعّال + نداء فشل (مهلة) => لا يجوز أن
    يُنسَب الغياب لـ"لا مفتاح" — يجب أن يذكر فشل النداء صراحة."""
    import silk_ai_judge as aj

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_ai_judge._call", return_value=None):
        out = aj.write_reviewed_report(
            {}, "x", {"verdict": "WATCH"}, "تمور", "هولندا")

    assert out["report"] is None
    assert "مفتاح" not in out["failure_reason"]
    assert "فشل" in out["failure_reason"] or "مهلة" in out["failure_reason"]


def test_run_loop_gap_message_distinguishes_key_vs_call_failure():
    import silk_llm_runtime as rt

    mission = {"key": "t", "name": "t", "allowed_tools": [],
              "instructions": "x"}
    ctx = {"market": _ref(), "product": "p", "hs_code": None,
          "extra_findings": [], "extra_context": ""}
    budget = {"tool_calls": 8, "max_output_tokens": 6000}

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_llm_runtime._call_tools", return_value=None):
        out_call_fail = rt._run_loop(mission, ctx, budget)
    assert "مفتاح" not in out_call_fail["gaps"][0]

    with _env(ANTHROPIC_API_KEY=None), \
         patch("silk_llm_runtime._call_tools", return_value=None):
        out_no_key = rt._run_loop(mission, ctx, budget)
    assert "مفتاح" in out_no_key["gaps"][0]


def test_ask_endpoint_call_failure_note_does_not_blame_key():
    import pytest
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    import api
    from fastapi.testclient import TestClient

    with _env(SILK_API_KEY=None, SILK_RATE_LIMIT="0", ANTHROPIC_API_KEY="test-key"):
        importlib.reload(api)
        client = TestClient(api.create_app())
        result = {"product": "تمور", "markets": [], "view": {}}
        with patch("silk_storage.get_analysis", return_value=result), \
             patch("silk_ai_judge.answer_about_analysis", return_value=None):
            r = client.post("/analyses/1/ask", json={"question": "س"})
    importlib.reload(api)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] is None
    assert "مفتاح" not in body["note"]


# ── ٣: بوابة الجودة ترصد فشل طبقة المحلل كاملة ────────────────────────────

def _all_missing_no_report_view():
    return {"deep_research": {
        "missions": {"trade_flow": {"failed": False, "summary": "ok",
                                    "findings": [{"value": 100.0,
                                                 "source": "x",
                                                 "confidence": 0.9,
                                                 "note": "n"}]}},
        "analyst": {"by_category": {}, "missing_categories": [
            "demand", "entry_cost", "price_competitiveness",
            "entry_door", "swot"]},
        "report": {"text": "", "review_cycles": 0, "unresolved_notes": []},
    }}


def test_quality_gate_fails_when_five_intersections_empty_and_report_absent():
    import silk_quality_gate as qg

    out = qg.run_quality_gate(_all_missing_no_report_view())
    checks = {f["check"] for f in out["findings"]}
    assert "analyst_layer_failed" in checks
    assert out["verdict"] == qg.FAIL


def test_quality_gate_check_absent_when_report_text_present():
    """الفحص الجديد يشترط غياب التقرير الكامل معاً — نص موجود، حتى لو
    كانت فئات ناقصة، لا يُطلَق هذا الفحص تحديداً (فحوصات أخرى تكفي)."""
    import silk_quality_gate as qg

    view = _all_missing_no_report_view()
    view["deep_research"]["report"]["text"] = "## 1. الخلاصة التنفيذية\nنص."
    out = qg.run_quality_gate(view)
    checks = {f["check"] for f in out["findings"]}
    assert "analyst_layer_failed" not in checks


def test_quality_gate_check_absent_when_only_some_categories_missing():
    import silk_quality_gate as qg

    view = _all_missing_no_report_view()
    view["deep_research"]["analyst"]["missing_categories"] = ["demand"]
    out = qg.run_quality_gate(view)
    checks = {f["check"] for f in out["findings"]}
    assert "analyst_layer_failed" not in checks


def test_quality_gate_still_passes_on_the_original_clean_fixture():
    """حارس انحدار: التثبيت لا يكسر الحالة النظيفة القائمة (بلا
    missing_categories معلنة إطلاقاً) — لا إيجابية زائفة."""
    import silk_quality_gate as qg

    clean = {"deep_research": {
        "missions": {"trade_flow": {"failed": False, "summary": "ok",
                                    "findings": [{"value": 100.0,
                                                 "source": "x",
                                                 "confidence": 0.9,
                                                 "note": "n"}]}},
        "analyst": {"by_category": {}},
        "report": {"text": "", "review_cycles": 0, "unresolved_notes": []},
    }}
    out = qg.run_quality_gate(clean)
    assert out["verdict"] == qg.PASS
    assert out["findings"] == []

"""اختبارات الموجة ٣ (V5): المحلل الشامل للسوق (silk_market_analyst) +
امتداد silk_synthesis لاستقبال تقييمه.

يغطي: تجميع نتائج البعثات بعلامة المصدر، تصنيف البنود بالفئة، إعلان
التقاطعات الناقصة الأدلة صراحة (لا حذف صامت)، خيوط correlation.py كسياق
غير قابل للاستشهاد المباشر، وأن synthesize() تمرّر التقييم للمرحلة ٢ فقط
دون المساس بالمرحلة ١ الحتمية. الشبكة مقطوعة حيث يلزم.
Run:  python3 -m pytest tests/ -q
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network


def _ref():
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Nigeria")
    return ref


def _mission_reports():
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    return {
        "trade_flow": AgentReport(
            "LLMAgent:trade_flow",
            [DataPoint(950000.0, "UN Comtrade", 0.9, "استيراد التمور 2023")],
            False, "ok"),
        "consumer_culture": AgentReport(
            "LLMAgent:consumer_culture",
            [DataPoint("طلب موسمي مرتفع في رمضان", "Web Search", 0.6, "ثقافة")],
            False, "ok"),
    }


def _findings_json(*rows, gaps=None):
    return json.dumps({"findings": list(rows), "gaps": gaps or [],
                       "summary": "تحليل"}, ensure_ascii=False)


def _msg_text(content):
    """نص الرسالة سواء كانت سلسلة خام أو كتل محتوى مُعلَّمة بـcache_control
    (المرحلة ٠ — silk_llm_runtime._mark_cache_boundary)."""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def test_source_reports_are_tagged_by_mission_key():
    import silk_market_analyst as sma

    tagged = sma._tag_source_reports(_mission_reports())
    notes = [dp.note for dp in tagged]
    assert any(n.startswith("[trade_flow]") for n in notes)
    assert any(n.startswith("[consumer_culture]") for n in notes)


def test_findings_grouped_by_category_and_gaps_declared():
    import silk_market_analyst as sma

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        text = _msg_text(messages[0]["content"])
        did = text[text.find("[dp"):].split("]")[0][1:]  # "dp1"
        rows = [
            {"claim": "طلب استدلالي معقول", "datapoint_ids": [did],
             "confidence": 0.6, "category": "demand"},
            {"claim": "تعريفة معتدلة", "datapoint_ids": [did],
             "confidence": 0.5, "category": "entry_cost"},
        ]
        return {"stop_reason": "end_turn",
               "content": [{"type": "text", "text": _findings_json(*rows)}]}

    with block_network(), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        out = sma.analyze_market(_ref(), "تمور", _mission_reports(),
                                 hs_code="080410")

    assert out["by_category"]["demand"], "demand category empty"
    assert out["by_category"]["entry_cost"], "entry_cost category empty"
    # الثلاث الباقية بلا أدلة => فجوة معلنة، لا حذف صامت.
    assert set(out["missing_categories"]) == {
        "price_competitiveness", "entry_door", "swot"}
    assert "تقاطعات ناقصة" in out["report"].summary


def test_correlation_threads_passed_as_narrative_context_not_citable():
    import silk_market_analyst as sma

    captured = []

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        captured.append(_msg_text(messages[0]["content"]))
        return {"stop_reason": "end_turn",
               "content": [{"type": "text", "text": _findings_json()}]}

    threads = {"competitor_threads": [{"name": "منافس تجريبي"}]}
    with block_network(), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        sma.analyze_market(_ref(), "تمور", _mission_reports(),
                           correlation_threads=threads)

    assert "منافس تجريبي" in captured[0]


def test_to_synthesis_input_is_json_serializable():
    import silk_market_analyst as sma

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        return {"stop_reason": "end_turn",
               "content": [{"type": "text", "text": _findings_json()}]}

    with block_network(), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        out = sma.analyze_market(_ref(), "تمور", _mission_reports())

    payload = sma.to_synthesis_input(out)
    json.dumps(payload, ensure_ascii=False)  # لا يرمي استثناءً


def test_synthesize_stage1_unaffected_by_analyst_assessment():
    from silk_synthesis import synthesize
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint

    reports = [AgentReport("A", [DataPoint(1.0, "s", 0.9, "n")], False, "ok")]
    without = synthesize(reports, product="p", market="m", with_ai=False)
    with_analyst = synthesize(reports, product="p", market="m", with_ai=False,
                              analyst_assessment={"summary": "x"})
    # المرحلة ١ الحتمية محايدة تماماً تجاه وجود تقييم المحلل — نفس القرار.
    assert without["verdict"] == with_analyst["verdict"]
    assert without["confidence"] == with_analyst["confidence"]
    assert "ai" not in with_analyst  # with_ai=False => لا مرحلة ٢ إطلاقاً


def test_synthesize_stage2_receives_analyst_assessment_when_present():
    from silk_synthesis import synthesize
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint

    captured = {}

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        captured["user"] = user
        return json.dumps({"verdict": "WATCH", "confidence": 0.5,
                           "reasoning": "ok"})

    reports = [AgentReport("A", [DataPoint(1.0, "s", 0.9, "n")], False, "ok")]
    with patch("silk_synthesis._call", side_effect=fake_call):
        result = synthesize(
            reports, product="تمور", market="نيجيريا", with_ai=True,
            analyst_assessment={"summary": "خمس تقاطعات مبنية على الأدلة"})

    assert result["ai"]["grounded_in_analyst"] is True
    assert "تقييم المحلل الشامل" in captured["user"]
    assert "خمس تقاطعات مبنية على الأدلة" in captured["user"]

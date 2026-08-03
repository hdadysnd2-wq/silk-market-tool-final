"""اختبارات الموجة ٦ (V5): تتبّع تشغيلات البحث العميق (silk_trace) + التنقيح.

يغطي: التتبّع no-op خارج trace_context، أحداث الجولات/الأدوات/الإنهاء
تُكتب بالترتيب الصحيح، تعقيم الأسرار يشمل كل نص متداخل (dict/list)، وضع
التنقيح الجاف (deep_research(dry_run=True, only_agent=...)) يشغّل بعثة
واحدة فقط، ولوحة تتبّع بلمحة (view["deep_research"]["missions"][k]["trace"])
تُستخرَج صحيحة من نص الملخّص. لا شبكة مطلوبة — كل نداء كلود مموَّه.
Run:  python3 -m pytest tests/ -q
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ref():
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Nigeria")
    return ref


def test_record_event_is_noop_outside_trace_context(tmp_path):
    import silk_trace

    silk_trace.record_event(kind="x")  # لا استثناء، لا ملف
    assert not os.path.exists(tmp_path / "anything.jsonl")
    assert silk_trace.active() is False


def test_trace_context_writes_events_and_read_trace_returns_them(tmp_path):
    import silk_trace

    with silk_trace.trace_context("t1", dir_path=str(tmp_path)):
        assert silk_trace.active() is True
        assert silk_trace.current_trace_id() == "t1"
        silk_trace.record_event(kind="a", n=1)
        silk_trace.record_event(kind="b", n=2)
    assert silk_trace.active() is False  # يُطفَأ عند الخروج من الكتلة

    events = silk_trace.read_trace("t1", dir_path=str(tmp_path))
    assert [e["kind"] for e in events] == ["a", "b"]
    assert all("ts" in e for e in events)


def test_secrets_are_redacted_recursively_in_nested_structures(tmp_path):
    import silk_trace

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-super-secret"}):
        with silk_trace.trace_context("t2", dir_path=str(tmp_path)):
            silk_trace.record_event(
                kind="tool_call",
                input={"query": "leak sk-super-secret here"},
                output=[{"note": "nested sk-super-secret leak"}])
    raw = (tmp_path / "t2.jsonl").read_text(encoding="utf-8")
    assert "sk-super-secret" not in raw
    assert "<ANTHROPIC_API_KEY>" in raw


def test_read_trace_missing_file_returns_empty_list(tmp_path):
    import silk_trace

    assert silk_trace.read_trace("nope", dir_path=str(tmp_path)) == []


def test_llm_runtime_records_llm_call_tool_call_and_finish_events(tmp_path):
    import silk_trace
    import silk_llm_runtime as rt

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        if tools:
            return {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "t1", "name": "web_search",
                 "input": {"query": "x"}}]}
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(
                {"findings": [], "gaps": [], "summary": "done"})}]}

    mission = {"key": "demo", "name": "تجريبي", "instructions": "test",
              "allowed_tools": ["web_search"]}
    with patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools), \
         silk_trace.trace_context("t3", dir_path=str(tmp_path)):
        rt.run_llm_agent(mission, _ref(), product="تمور",
                         budget={"tool_calls": 1})

    kinds = [e["kind"] for e in silk_trace.read_trace("t3", dir_path=str(tmp_path))]
    assert "llm_call" in kinds
    assert "tool_call" in kinds
    assert kinds[-1] == "finish"


def test_deep_research_dry_run_executes_only_the_named_mission(tmp_path):
    import silk_missions as sm

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(
                {"findings": [], "gaps": [], "summary": "dry"})}]}

    with patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        out = sm.deep_research(_ref(), product="تمور", hs_code="080410",
                               dry_run=True, only_agent="pricing_scout",
                               trace_dir=str(tmp_path))

    assert out["mode"] == "dry_run"
    assert out["mission"] == "pricing_scout"
    assert out["events"]
    assert os.path.exists(out["trace_path"])


def test_deep_research_dry_run_rejects_unknown_mission():
    import pytest
    import silk_missions as sm

    with pytest.raises(ValueError):
        sm.deep_research(_ref(), product="تمور", dry_run=True,
                         only_agent="not_a_real_mission")


def test_full_deep_research_run_traces_the_whole_run(tmp_path):
    import silk_missions as sm

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(
                {"findings": [], "gaps": [], "summary": "ok"})}]}

    with patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        out = sm.deep_research(_ref(), product="تمور", hs_code="080410",
                               trace_dir=str(tmp_path))

    assert out["mode"] == "full"
    assert len(out["reports"]) == 12
    assert os.path.exists(out["trace_path"])


def test_view_trace_summary_extracted_from_mission_summary_text():
    from silk_render import build_view
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint

    ok_report = AgentReport(
        "LLMAgent:trade_flow",
        [DataPoint("claim", "x", 0.9, "n")], False,
        "ok | فجوات: لا بيانات أسعار؛ لا بيانات مخاطر | أُسقطت 2 بند(ود) "
        "بلا استشهاد | نداءات أدوات: 5")
    disabled_report = AgentReport(
        "LLMMissionAgent:pricing_scout", [], True,
        "pricing_scout: معطّل من إعدادات الوكلاء — disabled by user setting")

    result = {
        "product": "تمور", "hs_code": "080410", "markets": [],
        "market": {"iso3": "NGA", "name_ar": "نيجيريا"},
        "deep_research": {
            "missions": {"trade_flow": ok_report,
                        "pricing_scout": disabled_report},
            "analyst": {"report": AgentReport("A", [], True, ""),
                       "by_category": {}, "missing_categories": []},
            "verdict": {}, "report": {}, "trace_id": "run-NGA-123",
        },
    }
    view = build_view(result)
    dr = view["deep_research"]
    assert dr["trace_id"] == "run-NGA-123"
    tf = dr["missions"]["trade_flow"]["trace"]
    assert tf == {"status": "succeeded", "tool_calls": 5, "dropped": 2, "gaps": 2}
    ps = dr["missions"]["pricing_scout"]["trace"]
    assert ps["status"] == "skipped"

"""E2/E3 (SPEC-v2, Command #6) — انحدار التكلفة والسرعة.

E2: بعثات الاستخلاص الاثنتا عشرة على النموذج السريع (Haiku)؛ المحلل الشامل
على النموذج الذكي (Opus) — توجيه لكل نداء لا نموذج واحد للكل.
E3: زمن الجدار لكل مرحلة + أكبر ثلاثة مصارف يظهران في data_economics
(المالك يقيس عليهما هدف < ١٠ دقائق؛ البعثات متوازية أصلاً).

Run: python3 -m pytest tests/test_cost_speed_e.py -q
"""
import json
import os
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── E2: توجيه النموذج ────────────────────────────────────────────────────
def test_missions_default_to_fast_model():
    import silk_llm_runtime as R
    from silk_ai_judge import _FAST_MODEL
    assert R._MISSION_MODEL == _FAST_MODEL  # بعثات على السريع افتراضياً


def test_run_llm_agent_passes_mission_model_to_loop():
    import silk_llm_runtime as R
    from silk_ai_judge import _FAST_MODEL
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Netherlands")
    captured = {}

    def fake_loop(mission, ctx, budget, timeout=None, model=None):
        captured["model"] = model
        return {"findings": [], "registry": {}}

    with patch.object(R, "_run_loop", side_effect=fake_loop):
        R.run_llm_agent({"key": "trade_flow", "name": "تجارة",
                         "instructions": "i", "allowed_tools": []}, ref)
    assert captured["model"] == _FAST_MODEL  # بعثة => سريع


def test_explicit_model_arg_overrides_mission_default():
    import silk_llm_runtime as R
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Netherlands")
    captured = {}

    def fake_loop(mission, ctx, budget, timeout=None, model=None):
        captured["model"] = model
        return {"findings": [], "registry": {}}

    with patch.object(R, "_run_loop", side_effect=fake_loop):
        R.run_llm_agent({"key": "market_analyst", "name": "محلل",
                         "instructions": "i", "allowed_tools": []}, ref,
                        model="claude-opus-4-8")
    assert captured["model"] == "claude-opus-4-8"


def test_analyst_routes_to_smart_model():
    import silk_market_analyst as A
    from silk_ai_judge import _MODEL
    from silk_market_resolver import resolve_market
    from silk_agents import AgentReport
    ref, _ = resolve_market("Netherlands")
    captured = {}

    def fake_agent(*a, **k):
        captured["model"] = k.get("model")
        return AgentReport("LLMAgent:market_analyst", [], False, "s")

    with patch.object(A, "run_llm_agent", side_effect=fake_agent):
        A.analyze_market(ref, "تمور", {}, hs_code="080410")
    assert captured["model"] == _MODEL  # المحلل => الذكي صراحةً


# ── E3: زمن المراحل ──────────────────────────────────────────────────────
def _fake_tools(system, messages, tools=None, max_tokens=None, model=None,
                timeout=None):
    return {"text": json.dumps({"findings": []}), "tool_calls": [],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 50, "output_tokens": 20}}


def _fake_call(system, user, max_tokens=1600, model=None, timeout=None):
    return json.dumps({"verdict": "WATCH", "confidence": 0.5, "reasoning": "ok"})


def _fake_writer(system, user, max_tokens=1600, model=None, timeout=None):
    return "## 1. الخلاصة التنفيذية\nتقرير تجريبي كامل مراجَع."


def test_stage_seconds_and_top_sinks_in_data_economics():
    from fastapi.testclient import TestClient
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "t", "SILK_API_KEY": "s",
                                 "SILK_RATE_LIMIT": "100000"}), \
            patch("silk_llm_runtime._call_tools", side_effect=_fake_tools), \
            patch("silk_synthesis._call", side_effect=_fake_call), \
            patch("silk_ai_judge._call", side_effect=_fake_writer), \
            patch("silk_data_layer._cached_get", return_value=None), \
            patch("silk_data_layer._http_get", side_effect=OSError("no net")), \
            patch("silk_storage._db_path", return_value=db):
        import api
        client = TestClient(api.create_app())
        hdr = {"X-API-Key": "s"}
        r = client.post("/research", headers=hdr, json={
            "product": "تمور", "market": "Nigeria", "hs_code": "080410",
            "persist": True, "async_run": True})
        assert r.status_code == 202
        aid = r.json()["analysis_id"]
        st = {}
        for _ in range(1500):
            st = client.get(f"/research/{aid}/status", headers=hdr).json()
            if st.get("status") and st["status"] != "running":
                break
            time.sleep(0.01)
        assert st.get("status") == "completed", st
        result = client.get(f"/analyses/{aid}", headers=hdr).json()
    econ = result.get("data_economics") or {}
    assert "stage_seconds" in econ and isinstance(econ["stage_seconds"], dict)
    assert "stage_top_sinks" in econ
    assert "stage_total_seconds" in econ
    # المراحل الأربع مرصودة بأزمنة غير سالبة.
    for stage in ("missions", "analyst", "synthesis", "writer"):
        assert stage in econ["stage_seconds"]
        assert econ["stage_seconds"][stage] >= 0
    # أكبر ثلاثة مصارف: بنية [{stage, seconds}] مرتّبة تنازلياً.
    sinks = econ["stage_top_sinks"]
    assert len(sinks) <= 3 and all("stage" in s and "seconds" in s for s in sinks)

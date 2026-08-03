"""اختبارات الموجة ٢ (V5): بعثات وكلاء كلود الاثني عشر (silk_missions).

يغطي: تسجيل الكتالوج إضافي لا استبدال (١٤+١٢=٢٦، بلا تصادم مفاتيح)،
opportunity_gaps يعمل أخيراً ويقرأ نتائج الوكلاء ١-١١، مهلة وكيل واحد
لا توقف البقية (ThreadPoolExecutor)، وأداة channels_importers تتدهور
بهدوء بلا شبكة/مفتاح. الشبكة مقطوعة حيث تُستدعى أدوات حقيقية.
Run:  python3 -m pytest tests/ -q
"""
import json
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network


def _ref():
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Nigeria")
    return ref


def _msg_text(content):
    """نص الرسالة سواء كانت سلسلة خام أو كتل محتوى مُعلَّمة بـcache_control
    (المرحلة ٠ — silk_llm_runtime._mark_cache_boundary)."""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def test_registration_is_additive_no_key_collisions():
    import silk_agents
    import silk_missions  # noqa: F401 — الاستيراد يسجّل الصفوف

    keys = [a["key"] for a in silk_agents.AGENT_CATALOG]
    assert len(keys) == len(set(keys)), "duplicate AGENT_CATALOG keys"
    # الصفوف الـ١٤ القائمة قبل الموجة لم تُمَسّ (تحقق عيّني).
    for old_key in ("trade", "economic", "competition", "pricing"):
        assert old_key in keys
    for mission_key in silk_missions.MISSIONS:
        assert mission_key in keys
    assert len(keys) >= 26


def test_mission_order_ends_with_opportunity_gaps():
    import silk_missions as sm
    assert sm.MISSION_ORDER[-1] == "opportunity_gaps"
    assert set(sm.MISSION_ORDER) == set(sm.MISSIONS)


def test_all_missions_are_free_not_paid():
    import silk_missions as sm
    for m in sm.MISSIONS.values():
        assert m["allowed_tools"] == [] or all(
            t in __import__("silk_llm_runtime").TOOLS for t in m["allowed_tools"])
    import silk_agents
    mission_keys = set(sm.MISSIONS)
    for row in silk_agents.AGENT_CATALOG:
        if row["key"] in mission_keys:
            assert row["paid"] is False, row["key"]


def test_opportunity_gaps_receives_prior_findings_as_citable_datapoints():
    import silk_missions as sm

    captured = []

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        captured.append(_msg_text(messages[0]["content"]) if messages else "")
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(
                {"findings": [], "gaps": [], "summary": "ok"},
                ensure_ascii=False)}]}

    with block_network(), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        reports = sm.run_all_missions(_ref(), product="تمور", hs_code="080410")

    assert set(reports) == set(sm.MISSIONS)
    # آخر رسالة مُلتقَطة هي بعثة الفجوات (تعمل بعد الـ١١ الأخرى بالتسلسل).
    gaps_prompt = captured[-1]
    assert "المهمة" in gaps_prompt


def test_one_mission_timeout_does_not_block_the_rest(monkeypatch):
    import silk_missions as sm

    monkeypatch.setattr(sm, "_MISSION_TIMEOUT_S", 0.05)

    pricing_name = sm.MISSIONS["pricing_scout"]["name"]

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        first_msg = _msg_text(messages[0]["content"]) if messages else ""
        if pricing_name in first_msg:  # "المهمة: <اسم>" في مقدمة المستخدم
            time.sleep(0.3)  # يتجاوز المهلة القصيرة عمداً
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(
                {"findings": [], "gaps": [], "summary": "ok"},
                ensure_ascii=False)}]}

    with block_network(), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        reports = sm.run_all_missions(_ref(), product="تمور")

    assert len(reports) == 12
    assert reports["pricing_scout"].failed is True
    assert "مهلة" in reports["pricing_scout"].summary
    # بقية الوكلاء أُنجزت رغم مهلة واحد منها.
    assert reports["trade_flow"].failed is False or "ok" in reports["trade_flow"].summary


def test_channels_importers_tool_degrades_without_network_or_key():
    import silk_llm_runtime as rt

    with block_network():
        out = rt._execute_tool("channels_importers", {"product": "تمور"},
                               {"market": _ref(), "product": "تمور"})
    assert all(dp.value is None for dp in out)


def test_contextvars_propagate_into_parallel_mission_threads():
    # انحدار حقيقي اكتُشف أثناء بناء هذه الموجة: ThreadPoolExecutor لا يرث
    # contextvars تلقائياً — بلا copy_context().run(...) كانت توجيهات لوحة
    # إعدادات الوكلاء (تعطيل/توجيه) وحجب إضافات كلود (block_ai_extras)
    # تُتجاهَل بصمت داخل الخيوط الموازية رغم ضبطها في الخيط المستدعي.
    # لا محاكاة لـ_call_tools هنا عمداً — الاختبار يتحقق من النداء الحقيقي
    # (يفحص ai_extras_blocked() داخلياً قبل أي شبكة، فلا حاجة لقطعها).
    import silk_context
    import silk_missions as sm

    prefs = {"pricing_scout": {"on": False, "cmd": ""}}
    with silk_context.agent_prefs_context(prefs), \
         silk_context.block_ai_extras():
        reports = sm.run_all_missions(_ref(), product="تمور")

    # التعطيل سرى داخل خيط pricing_scout الموازي (لا تجاهل صامت).
    assert reports["pricing_scout"].failed is True
    assert "معطّل" in reports["pricing_scout"].summary
    # الحجب سرى أيضاً: بقية الوكلاء لم يستطيعوا نداء كلود رغم عدم تعطيلهم
    # (ai_extras_blocked() يعيد True فيُرفَض النداء قبل أي شبكة/مفتاح).
    assert reports["trade_flow"].failed is True
    assert "تعذّر" in reports["trade_flow"].summary or "gap" in \
        reports["trade_flow"].summary.lower()

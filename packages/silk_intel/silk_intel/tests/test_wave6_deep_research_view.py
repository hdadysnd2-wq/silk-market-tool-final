"""اختبارات الموجة ٤ج (V5): قسم البحث العميق في build_view (silk_render).

يغطي: تحليل /analyze عادي (بلا deep_research) لا يتأثر إطلاقاً، القسم
الإضافي يُبنى صحيحاً من AgentReport حيّة، تمييزه عن row['research'] القائم
(لا تصادم دلالي)، والمختصر/الترويسة/الحدود تعكس البحث العميق حين يوجد.
Run:  python3 -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mission_reports():
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    return {
        "trade_flow": AgentReport(
            "LLMAgent:trade_flow",
            [DataPoint(950000.0, "UN Comtrade", 0.9, "استيراد 2023")],
            False, "ok"),
        "pricing_scout": AgentReport("LLMAgent:pricing_scout", [], True,
                                     "لا نتائج"),
    }


def _deep_research_result():
    from silk_market_resolver import resolve_market
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint

    ref, _ = resolve_market("Nigeria")
    analyst_report = AgentReport(
        "LLMAgent:market_analyst",
        [DataPoint("طلب استدلالي معقول", "x", 0.6, "[demand] مبني على: ...")],
        False, "تحليل")
    return {
        "product": "تمور", "hs_code": "080410", "year": None,
        "market": {"iso3": ref.iso3, "m49": ref.m49, "iso2": ref.iso2,
                  "name_en": ref.name_en, "name_ar": ref.name_ar},
        "markets": [],
        "deep_research": {
            "missions": _mission_reports(),
            "analyst": {"report": analyst_report,
                       "by_category": {"demand": analyst_report.findings,
                                      "entry_cost": [], "price_competitiveness": [],
                                      "entry_door": [], "swot": []},
                       "missing_categories": ["entry_cost",
                                              "price_competitiveness",
                                              "entry_door", "swot"]},
            "verdict": {"verdict": "PRELIMINARY GO — مبدئي إيجابي",
                       "ai": {"verdict": "WATCH", "confidence": 0.5}},
            "report": {"report": "## 1. الخلاصة التنفيذية\nنص.",
                      "review_cycles": 2, "unresolved_notes": ["ملاحظة"]},
        },
    }


def test_classic_analyze_result_has_no_deep_research_section():
    from silk_render import build_view

    classic = {"product": "تمور", "hs_code": "080410", "markets": [
        {"iso3": "NGA", "country": "نيجيريا", "total_score": 0.5,
         "confidence": 0.5, "components": {}}]}
    view = build_view(classic)
    assert view["deep_research"] is None


def test_deep_research_section_built_from_live_agent_reports():
    from silk_render import build_view

    view = build_view(_deep_research_result())
    dr = view["deep_research"]
    assert dr is not None
    assert set(dr["missions"]) == {"trade_flow", "pricing_scout"}
    assert dr["missions"]["trade_flow"]["findings"][0]["value"] == 950000.0
    assert dr["missions"]["pricing_scout"]["failed"] is True
    assert dr["analyst"]["missing_categories"] == [
        "entry_cost", "price_competitiveness", "entry_door", "swot"]
    assert dr["report"]["review_cycles"] == 2
    assert dr["report"]["unresolved_notes"] == ["ملاحظة"]


def test_by_category_carries_confidence_badge_not_raw_number():
    """P2 (مراجعة أرقام منفصلة بلا معنى): كل عنصر في by_category يحمل
    الآن confidence_badge محسوبة في النموذج القانوني نفسه — الواجهة تعرضها
    مباشرة بلا تصنيف خام في JS العميل ولا رقم ثقة عشري خام."""
    from silk_render import build_view
    view = build_view(_deep_research_result())
    demand = view["deep_research"]["analyst"]["by_category"]["demand"]
    assert demand[0]["confidence"] == 0.6
    assert demand[0]["confidence_badge"] == "◐ ثانوي"


def test_deep_research_key_distinct_from_existing_stage3_research_key():
    # تصادم تسمية محتمل: row["research"] له معنى مختلف تماماً (حزمة
    # الوكلاء الثمانية الحتمية، silk_research.py) — يجب ألا يتقاطعا.
    from silk_render import build_view

    result = _deep_research_result()
    view = build_view(result)
    assert "research" not in view          # لم يُبنَ من صفوف markets أصلاً
    assert view["deep_research"] is not None
    assert view["markets"] == []


def test_header_brief_and_limits_reflect_deep_research():
    from silk_render import build_view

    view = build_view(_deep_research_result())
    assert view["header"]["target_market"] in ("نيجيريا", "Nigeria")
    assert any("WATCH" in b or "بحث عميق" in b for b in view["brief"])
    # بلاغ منتج من المالك: المفتاح snake_case الخام (pricing_scout) لا
    # يجوز أن يظهر في حدود معروضة للعميل — اسم البعثة العربي يحل محله.
    assert not any("pricing_scout" in x for x in view["limits"])
    assert any("تحليل الأسعار" in x for x in view["limits"])
    # سدّ تسريب (الطبقة ٩): مفتاح تقاطع خام إنجليزي ("entry_cost") كان
    # يصل هذا الحدّ حرفياً — الاسم التجاري العربي يحل محله الآن.
    assert not any("entry_cost" in x for x in view["limits"])
    assert any("تكلفة وصعوبة الدخول" in x for x in view["limits"])
    assert any("ملاحظة" in x for x in view["limits"])


def test_next_step_paid_layer_hint_only_on_go_verdict():
    from silk_render import build_view

    go_result = _deep_research_result()
    go_result["deep_research"]["verdict"] = {
        "verdict": "PRELIMINARY GO — مبدئي إيجابي"}
    view = build_view(go_result)
    assert "تعميق" in view["deep_research"]["next_step"]

    nogo_result = _deep_research_result()
    nogo_result["deep_research"]["verdict"] = {
        "verdict": "NO-GO (insufficient data)"}
    view2 = build_view(nogo_result)
    assert view2["deep_research"]["next_step"] is None


def test_reloaded_plain_dict_shape_also_works_not_only_live_dataclasses():
    # بعد إعادة تحميل من التخزين (json_blob) تصير AgentReport/DataPoint
    # قواميس عادية — يجب أن يعمل build_view بلا استثناء أيضاً.
    from silk_render import build_view

    result = _deep_research_result()
    import dataclasses
    result["deep_research"]["missions"] = {
        k: dataclasses.asdict(v) for k, v in
        result["deep_research"]["missions"].items()}
    result["deep_research"]["analyst"]["report"] = dataclasses.asdict(
        result["deep_research"]["analyst"]["report"])
    view = build_view(result)
    assert view["deep_research"]["missions"]["trade_flow"]["findings"][0][
        "value"] == 950000.0

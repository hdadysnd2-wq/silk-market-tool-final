"""PART B2 (أمر العمل الرئيس) — التقاطعات الخمس تظهر «بلا أدلة كافية» رغم
مساهمة البعثات 40/40. السبب غير قابل للحسم إحصائياً بلا مدوّنة حيّة: فشل نداء
المحلل (صفر نتائج)؟ نتائج بلا وسم [فئة] (انجراف صيغة)؟ وسم بفئة خارج القائمة؟

بدل التخمين (نمط الحادثة #8: عند غياب الدليل اشحن أداة قياس لا حزراً)، نُشحن
تشخيصاً ذاتياً يُخزَّن في المدوّنة ويظهر في `GET /analyses/{id}` عبر
`view.deep_research.analyst.diagnostics` — فالحادثة القادمة تُشخِّص نفسها.

هذا الملف يقفل سلوك التشخيص (لا يزعم إصلاح السبب الحيّ — مُعلَن NOT DONE حتى
تصل مدوّنة حيّة تكشف أيّ الأسباب الثلاثة).

Run: python3 -m pytest tests/test_analyst_intersections_diagnostics_b2.py -q
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mk(findings, failed=False, summary="تحليل"):
    from silk_agents import AgentReport
    return AgentReport("LLMAgent:market_analyst", findings, failed, summary)


def _dp(value, note):
    from silk_data_layer import DataPoint
    return DataPoint(value, "src", 0.7, note)


def _run_analyze(report):
    """شغّل analyze_market مع تثبيت نداء المحلل ليعيد `report` المُعطى."""
    import silk_market_analyst as A
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Netherlands")
    with patch.object(A, "run_llm_agent", return_value=report):
        return A.analyze_market(ref, "تمور", {}, hs_code="080410")


def test_diagnostics_flags_analyst_call_failure_all_missing():
    """نداء المحلل فشل (failed=True، صفر نتائج) => السبب المُعلَن
    analyst_call_failed، لا يُخلَط بانجراف التصنيف."""
    out = _run_analyze(_mk([], failed=True))
    d = out["diagnostics"]
    assert d["raw_findings"] == 0 and d["binned"] == 0
    assert d["analyst_failed"] is True
    assert d["all_missing_cause"] == "analyst_call_failed"
    assert out["missing_categories"] == list(__import__(
        "silk_market_analyst").REQUIRED_CATEGORIES)


def test_diagnostics_flags_format_drift_findings_present_but_uncategorized():
    """المحلل أنتج نتائج حقيقية لكن بلا وسم [فئة] (انجراف صيغة) => كلها غير
    مصنَّفة، والسبب المُعلَن يميّز هذا عن فشل النداء تماماً."""
    findings = [_dp("واردات 61 مليون", "رقم بلا وسم فئة"),
                _dp("نمو 9%", "أيضاً بلا وسم")]
    out = _run_analyze(_mk(findings))
    d = out["diagnostics"]
    assert d["raw_findings"] == 2 and d["binned"] == 0
    assert d["uncategorized"] == 2 and d["analyst_failed"] is False
    assert d["all_missing_cause"] == "findings_present_but_uncategorized"


def test_diagnostics_healthy_binning_has_no_all_missing_cause():
    """تصنيف سليم (وسوم [demand]/[swot]...) => لا سبب «كل فارغة»، والعدّاد
    يطابق الواقع (نمط التطبيع #5 لا يزال يعمل — Demand بحرف كبير تُصنَّف)."""
    findings = [_dp("طلب مرصود", "[demand] ثقافة استهلاك"),
                _dp("موقع تنافسي", "[Price_Competitiveness] هامش"),  # حرف كبير
                _dp("تحليل", "[SWOT] قوة")]
    out = _run_analyze(_mk(findings))
    d = out["diagnostics"]
    assert d["raw_findings"] == 3 and d["binned"] == 3
    assert d["all_missing_cause"] is None
    assert "demand" not in out["missing_categories"]
    assert "price_competitiveness" not in out["missing_categories"]


def test_diagnostics_surface_in_build_view_for_owner_inspection():
    """التشخيص يصل `view.deep_research.analyst.diagnostics` — يُقرأ من
    GET /analyses/{id} مباشرة بلا مدوّنة خام."""
    from silk_render import build_view
    from silk_market_analyst import to_synthesis_input
    analyst_out = _run_analyze(_mk([], failed=True))
    result = {
        "product": "تمور", "hs_code": "080410", "markets": [],
        "deep_research": {
            "missions": {}, "analyst": analyst_out,
            "verdict": {"verdict": "WATCH", "ai": {"verdict": "WATCH"}},
            "report": {"report": "## 1. الخلاصة\nنص.", "review_cycles": 1,
                      "unresolved_notes": []},
        },
    }
    diag = build_view(result)["deep_research"]["analyst"]["diagnostics"]
    assert isinstance(diag, dict) and "raw_findings" in diag
    assert diag["all_missing_cause"] == "analyst_call_failed"

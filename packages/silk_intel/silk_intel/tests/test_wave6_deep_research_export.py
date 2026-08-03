"""اختبارات الموجة ٤د (V5): تصدير البحث العميق (render_docx/render_brief).

يغطي: تقرير /analyze الكلاسيكي بلا تغيير إطلاقاً (لا قسم بحث عميق يظهر)،
المختصر يعرض تقاطعات المحلل بدل components_detail الفارغة، وWord يحتوي
جدول البعثات + التقاطعات الخمسة + نص التقرير المقسَّم بعناوين + ملاحظات
المراجعة غير المحلولة.
Run:  python3 -m pytest tests/ -q
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import docx_all_text


def _deep_research_result():
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    from silk_market_resolver import resolve_market

    ref, _ = resolve_market("Nigeria")
    analyst_report = AgentReport(
        "LLMAgent:market_analyst",
        [DataPoint("طلب استدلالي معقول", "x", 0.6, "[demand] ...")],
        False, "تحليل")
    return {
        "product": "تمور", "hs_code": "080410", "year": None,
        "market": {"iso3": ref.iso3, "m49": ref.m49, "iso2": ref.iso2,
                  "name_en": ref.name_en, "name_ar": ref.name_ar},
        "markets": [],
        "deep_research": {
            "missions": {
                "trade_flow": AgentReport(
                    "LLMAgent:trade_flow",
                    [DataPoint(950000.0, "UN Comtrade", 0.9, "n")],
                    False, "ok")},
            "analyst": {"report": analyst_report,
                       "by_category": {"demand": analyst_report.findings,
                                      "entry_cost": [], "price_competitiveness": [],
                                      "entry_door": [], "swot": []},
                       "missing_categories": ["entry_cost",
                                              "price_competitiveness",
                                              "entry_door", "swot"]},
            # WP-1: الحكم المعروض من الحقل الحتمي حصراً.
            "verdict": {"verdict": "WATCH", "confidence": 0.5,
                       "ai": {"verdict": "WATCH", "confidence": 0.5,
                             "reasoning": "سبب تجريبي"}},
            "report": {"report": ("## 1. الخلاصة التنفيذية\nنص تجريبي.\n"
                                  "## 2. الديموغرافيا والاقتصاد\nنص آخر."),
                      "review_cycles": 2, "unresolved_notes": ["ملاحظة"]},
        },
    }


def test_classic_analyze_docx_has_no_deep_research_section(monkeypatch):
    from silk_render import build_view
    from silk_reports import render_docx

    monkeypatch.setenv("SILK_HERMETIC", "1")
    classic = {"product": "تمور", "hs_code": "080410", "markets": [
        {"iso3": "NGA", "country": "نيجيريا", "total_score": 0.5,
         "confidence": 0.5, "components": {}}]}
    view = build_view(classic)
    path = os.path.join(tempfile.mkdtemp(), "classic.docx")
    render_docx(view, path)
    text = docx_all_text(path)
    assert "قسم البحث العميق" not in text


def test_deep_research_docx_has_missions_table_intersections_and_report(
        monkeypatch):
    from silk_render import build_view
    from silk_reports import render_docx

    monkeypatch.setenv("SILK_HERMETIC", "1")
    view = build_view(_deep_research_result())
    path = os.path.join(tempfile.mkdtemp(), "deep.docx")
    render_docx(view, path)
    text = docx_all_text(path)
    assert "قسم البحث العميق" in text
    # إصلاح تسريب السباكة: الاسم التجاري العربي (label) بدل مفتاح snake_case
    # الخام — راجع tests/test_report_plumbing_leaks.py
    from silk_missions import MISSIONS
    assert MISSIONS["trade_flow"]["name"] in text
    assert "trade_flow" not in text
    assert "الطلب الفعلي القابل للتوجيه" in text
    assert "نص تجريبي" in text
    assert "نص آخر" in text
    assert "ملاحظة" in text  # ملاحظة المراجعة غير المحلولة
    assert "دليل غير كافٍ" in text  # entry_cost فارغ => فجوة معلنة لا حذف


def test_deep_research_brief_uses_analyst_intersections_not_empty_components():
    from silk_render import build_view
    from silk_reports import render_brief

    view = build_view(_deep_research_result())
    brief = render_brief(view)
    assert "طلب استدلالي معقول" in brief
    assert "نيجيريا" in brief
    # الحكم يصل مُعرَّباً لا رمز الآلة الخام (سدّ تسريب: مسار /research كان
    # يُظهر "WATCH"/"GO" حرفياً في المختصر الجوال بينما المسار الكلاسيكي
    # يُترجمه أصلاً عبر silk_narrative.verdict_ar) — راجع "مراقبة السوق"
    # في VERDICT_AR.
    assert "مراقبة السوق" in brief
    assert "WATCH" not in brief


def test_classic_brief_unaffected_by_deep_research_branch():
    from silk_render import build_view
    from silk_reports import render_brief

    classic = {"product": "تمور", "hs_code": "080410", "markets": [
        {"iso3": "NGA", "country": "نيجيريا", "total_score": 0.5,
         "confidence": 0.5, "components": {
             "market_size": {"value": 1000000.0, "source": "UN Comtrade"}}}]}
    view = build_view(classic)
    brief = render_brief(view)
    assert "نيجيريا" in brief
    assert "بحث عميق" not in brief

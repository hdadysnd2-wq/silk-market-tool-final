"""اختبارات PR-D (R2 تفعيل الدردشة فوق الدراسة): analysis_context كان يقرأ
شكل /analyze حصراً، فتُجيب دردشة «اسأل عن الدراسة» عن الدراسات العميقة من
سياق شبه فارغ. الآن يُؤسِّس على كامل الدراسة العميقة — حقائق البعثات بمصادرها،
تقاطعات المحلل، الحكم، والتقرير المكتوب. لا اختلاق: كل رقم بمصدره.

كما تُفعَّل البطاقة في واجهة الدراسة العميقة (renderDeepResearch).
Run:  python3 -m pytest tests/test_r2_chat_grounding.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_agents import AgentReport  # noqa: E402
from silk_data_layer import DataPoint  # noqa: E402


def _dp(value, source, note="ملاحظة"):
    return DataPoint(value, source, 0.8, note, "2026-07-02")


def _deep_result():
    """نتيجة /research عميقة مصغّرة — نفس شكل البيانات الذي يبنيه المسار الحقيقي."""
    missions = {
        "trade_flow": AgentReport("LLMAgent:trade_flow", [
            _dp("واردات هولندا من التمور 38 مليون دولار (2023)", "UN Comtrade")],
            False, "تدفقات مؤكَّدة"),
        "customs_requirements": AgentReport("LLMAgent:customs_requirements", [
            _dp("تسجيل منشأة معتمدة EU 2017/625 إلزامي", "EU 2017/625")],
            False, "اشتراط أهلية حرج"),
    }
    demand = [_dp("الجالية المسلمة نحو 1.0 مليون نسمة", "مرجع الديموغرافيا")]
    analyst = AgentReport("LLMAgent:market_analyst", demand, False, "تحليل مكتمل")
    return {
        "product": "تمر", "hs_code": "080410", "year": 2023,
        "market": {"iso3": "NLD", "m49": "528", "iso2": "NL",
                   "name_en": "Netherlands", "name_ar": "هولندا"},
        "markets": [],
        "deep_research": {
            "trace_id": "t-nld",
            "missions": missions,
            "analyst": {"report": analyst, "by_category": {"demand": demand},
                        "missing_categories": []},
            "verdict": {"verdict": "CONDITIONAL-GO",
                        "ai": {"verdict": "CONDITIONAL-GO", "confidence": 0.66,
                               "reasoning": "أدلة تدعم دخولاً مشروطاً"}},
            "report": {"report": "## 1. الخلاصة\nنص التقرير المكتوب للدراسة هنا.",
                       "review_cycles": 1, "unresolved_notes": []},
        },
    }


def test_analysis_context_grounds_deep_research_study():
    """جوهر R2: سياق الدردشة يشمل حقائق البعثات + الحكم + التقرير المكتوب —
    لا العنوان وحده كما كان."""
    from silk_render import analysis_context
    ctx = analysis_context(_deep_result())
    assert "التقرير المكتوب للدراسة" in ctx
    assert "نص التقرير المكتوب للدراسة هنا" in ctx      # نص التقرير الفعلي
    assert "واردات هولندا من التمور 38 مليون دولار" in ctx   # حقيقة بعثة
    assert "حكم الدراسة" in ctx                          # الحكم
    assert "تقاطع" in ctx                                # تقاطع المحلل


def test_analysis_context_deep_research_facts_carry_sources():
    """لا اختلاق: كل حقيقة بعثة تحمل مصدرها في السياق."""
    from silk_render import analysis_context
    ctx = analysis_context(_deep_result())
    assert "[المصدر: UN Comtrade]" in ctx
    assert "EU 2017/625" in ctx


def test_analysis_context_deep_research_much_richer_than_header_only():
    """قياس الفرق: السياق العميق أطول بكثير من مجرد العنوان + المختصر."""
    from silk_render import analysis_context
    deep = analysis_context(_deep_result())
    # بلا deep_research يبقى شكل /analyze نحيلاً (لا أسواق، لا مكوّنات)
    shallow = analysis_context({
        "product": "تمر", "hs_code": "080410", "year": 2023,
        "market": {"iso3": "NLD", "name_ar": "هولندا"}, "markets": []})
    assert len(deep) > len(shallow) + 200


def test_analysis_context_still_serves_analyze_shape():
    """عدم انحدار: نتيجة /analyze الكلاسيكية ما زالت تُنتج سطر المكوّن بمصدره."""
    from silk_render import analysis_context
    result = {
        "product": "تمر", "hs_code": "080410", "year": 2023,
        "market": {"iso3": "NLD", "name_ar": "هولندا"},
        "markets": [{
            "country": "هولندا", "iso3": "NLD", "total_score": 61.0,
            "confidence": 0.8,
            "components": {"market_size": _dp(38000000.0, "UN Comtrade")},
        }],
    }
    ctx = analysis_context(result)
    assert "UN Comtrade" in ctx
    assert "هولندا" in ctx


def test_deep_research_ui_wires_ask_card():
    """الواجهة: بطاقة «اسأل عن الدراسة» صارت داخل renderDeepResearch (كانت
    تُبنى بعد return فلا تظهر للدراسات العميقة إطلاقاً)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "web", "index.html"), encoding="utf-8").read()
    idx = html.index("function renderDeepResearch")
    end = html.index("function renderBoard")
    block = html[idx:end]
    assert "اسأل عن الدراسة" in block
    assert "askAnalysis" in block          # موصولة بنفس دالة الإرسال
    assert 'id="askBox"' in block and 'id="askBtn"' in block

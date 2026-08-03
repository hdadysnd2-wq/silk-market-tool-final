"""اختبارات طبقة السرد (P1) — silk_narrative: قيم الآلة لا تصل وجه المستخدم.

مواصفة المالك: كل درجة معيارية 0–1 تُترجم لحالة لغوية أو تُخفى؛ المعجم
إلزامي (CONDITIONAL-GO → دخول مشروط، HHI → تركّز الموردين…)؛ الخلاصة
التنفيذية ٣ فقرات بشرية بلا score ولا اسم وكيل ولا شرط كود؛ والقيمة
الغائبة «—» هادئة بلا شعار. عرض صرف — القيم نفسها لا تتغير أبداً.
Run:  python3 -m pytest tests/test_p1_narrative.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_narrative as N  # noqa: E402
from silk_data_layer import DataPoint  # noqa: E402


def test_evidence_badge_relocated_to_narrative():
    """شارة الأدلة الثلاثية رُحِّلت من silk_reports إلى silk_narrative (P2)
    لتُستعمل من نموذج العرض القانوني (silk_render._deep_research_view) لا
    من طبقة عرض النص وحدها؛ نفس جدول العتبات الذي يحميه
    tests/test_wave9_sellable_report.py::test_evidence_badge_thresholds
    عبر توافق خلفي (silk_reports._evidence_badge)."""
    assert N.evidence_badge(0.9) == "✓ موثّق"
    assert N.evidence_badge(0.8) == "✓ موثّق"
    assert N.evidence_badge(0.79) == "◐ ثانوي"
    assert N.evidence_badge(0.5) == "◐ ثانوي"
    assert N.evidence_badge(0.49) == "○ غير متحقق"
    assert N.evidence_badge(None) == "○ غير متحقق"


def test_verdict_glossary_never_leaks_machine_codes():
    assert N.verdict_ar("CONDITIONAL-GO") == "دخول مشروط"
    assert N.verdict_ar("GO") == "التوصية بالدخول"
    assert N.verdict_ar("NO-GO") == "عدم الدخول حالياً"
    assert N.verdict_ar("PRELIMINARY GO — دخول واعد") == "توصية أولية بالدخول"
    assert "بيانات غير كافية" in N.verdict_ar("NO-GO (insufficient data)")
    assert N.verdict_ar(None) == "تعذّر إصدار توصية"


def test_country_names_arabic_for_all_silk_markets():
    import silk_market_ranker as R
    missing = [c["iso3"] for c in R.COUNTRIES
               if c["iso3"] not in N.COUNTRY_AR]
    assert not missing, f"COUNTRY_AR missing: {missing}"
    assert N.country_ar("KWT") == "الكويت"
    assert N.country_ar("China") == "الصين"          # اسم إنجليزي أيضاً


def test_market_component_lines_handles_fetch_failed_and_hides_raw_hhi():
    """market_component_lines (سابقاً _top_drivers الخاصة بالسوق الأول فقط)
    تعمل الآن لأي سوق في الترتيب؛ تعذّر الجلب يُذكر صراحة لا يُسقَط صامتاً،
    وHHI الخام لا يصل الجملة أبداً."""
    market = {
        "components_detail": [
            {"name": "market_size", "value": None, "status": "fetch_failed",
             "source": "UN Comtrade"},
            {"name": "saudi_position", "value": 16.69, "source": "UN Comtrade"},
            {"name": "competition", "value": 0.0838, "source": "UN Comtrade"},
        ],
        "trend": {"growth_pct": 291.3, "cagr_pct": 25.5, "source": "UN Comtrade"},
    }
    lines = N.market_component_lines(market)
    joined = "\n".join(lines)
    assert "تعذّر الجلب" in joined
    assert "0.0838" not in joined
    assert "16.69%" in joined and "المصدر: UN Comtrade" in joined


def test_competition_phrase_hides_raw_hhi():
    open_txt = N.competition_phrase(0.08, top_share_pct=16.7, n_suppliers=43)
    assert "مفتوحة" in open_txt and "0.08" not in open_txt
    assert "43" in open_txt and "16.7%" in open_txt
    assert "التركّز" in N.competition_phrase(0.5) \
        or "يهيمنان" in N.competition_phrase(0.5)
    assert N.competition_phrase(None) == "غير متوفر"


def test_confidence_and_money_and_growth_formats():
    assert N.confidence_phrase(0.31) == "منخفضة (31%)"
    assert N.confidence_phrase(0.91) == "عالية (91%)"
    assert N.confidence_phrase(None) == "غير محسوبة"
    assert N.fmt_money(48_537_942) == "48.5 مليون دولار"
    assert N.fmt_money(789_206) == "789 ألف دولار"
    assert N.fmt_money(None) == "—"
    g = N.growth_phrase(25.5, 291.3, years="2019–2025")
    assert "معدل نمو سنوي مركّب 25.5%" in g and "CAGR" not in g


def _view():
    """نموذج عرض مصغّر بحقول محسوبة حقيقية الشكل — لا شبكة."""
    return {
        "decision": {"verdict": "CONDITIONAL-GO", "confidence": 0.52,
                     "market": "Kuwait"},
        "limits": ["KWT: demand_capacity missing (no income signal)"],
        "markets": [{
            "iso3": "KWT", "country": "Kuwait", "score": 0.85,
            "components_detail": [
                {"name": "market_size", "value": 789206.0,
                 "source": "UN Comtrade"},
                {"name": "saudi_position", "value": 16.69,
                 "source": "UN Comtrade"},
                {"name": "competition", "value": 0.0838,
                 "source": "UN Comtrade"},
            ],
            "trend": {"growth_pct": 291.3, "cagr_pct": 25.5,
                      "source": "UN Comtrade"},
        }],
    }


def test_exec_summary_three_human_paragraphs_no_machine_values():
    paras = N.exec_summary(_view())
    assert len(paras) == 3
    joined = "\n".join(paras)
    # فقرة التوصية بالعربية وباسم السوق العربي.
    assert "دخول مشروط" in paras[0] and "الكويت" in paras[0]
    # لا رمز آلة، لا درجة معيارية، لا اسم وكيل/مقياس داخلي، لا شرط كود.
    for banned in ("CONDITIONAL-GO", "score", "0.85", "0.0838", "hhi", "HHI",
                   "TradeFlowAgent", "market_size", "demand_capacity"):
        assert banned not in joined, banned
    # الأساس التجاري من الأرقام المرصودة بصيغة بشرية + المصدر.
    assert "ألف دولار" in paras[1] and "UN Comtrade" in paras[1]
    assert "16.69%" in paras[1]
    # فقرة النواقص تترجم اسم المقياس الداخلي.
    assert "دخل الفرد" in paras[2]


def test_brief_lines_carry_sources_not_ratios():
    lines = N.brief_lines(_view())
    joined = "\n".join(lines)
    assert "دخول مشروط" in lines[0]
    assert "المصدر: UN Comtrade" in joined
    assert "0.0838" not in joined            # HHI الخام لا يظهر أبداً


def test_render_brief_has_no_raw_hhi_or_slogans():
    from silk_render import build_view
    from silk_reports import render_brief
    res = {"product": "عسل", "hs_code": "040900", "hs_confidence": 1.0,
           "year": 2025, "classified": True,
           "markets": [{"country": "Kuwait", "iso3": "KWT", "m49": "414",
                        "total_score": 0.85, "confidence": 1.0,
                        "components": {
                            "market_size": DataPoint(789206.0, "UN Comtrade",
                                                     0.7, "total"),
                            "competition": DataPoint(0.0838, "UN Comtrade",
                                                     0.7, "HHI"),
                        }}]}
    brief = render_brief(build_view(res))
    assert "0.0838" not in brief             # تسريب HHI الخام (انحدار مقفول)
    for slogan in ("لا اختلاق", "معلنة لا مخمّنة", "قرار أوّلي لا نهائي",
                   "الفجوات معلنة"):
        assert slogan not in brief, slogan

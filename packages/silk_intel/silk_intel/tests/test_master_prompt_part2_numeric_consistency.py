"""Master Prompt Part 2 §A3/§C — تناقضٌ رقميٌّ داخليّ (سجل الأدلة مقابل المتن).

المثال المكتشف بالمواصفة: واردات 17K$ في متن التقرير مقابل 11.88 مليون$ في
سجل الأدلة — نسبة > 3× بلا تفسير => فشل داخلي قبل التسليم. هذا الملف يقفل
`silk_quality_gate._check_evidence_body_numeric_consistency` على: (أ) تعارضٌ
مصطنَع يطابق المثال حرفياً يُفشِل الحكم، (ب) تناقضٌ **مُفسَّر** صراحةً في
نافذته المحلية (مدوّنة الكويت القانونية — سعر التجزئة/الجملة) لا يُفشِل هذا
الفحص تحديداً (فحصٌ آخر موجودٌ أصلاً يتولى تفسير ذاك التناقض)، و(ج) رقمان
متفقان لا يُطلقان شيئاً.

Run: python3 -m pytest tests/test_master_prompt_part2_numeric_consistency.py -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.canonical_kuwait_peanut_butter import kuwait_research_blob  # noqa: E402


def _dr(report_text: str, evidence_value: float, note: str = "واردات 2023"):
    return {
        "missions": {"trade_flow": {"agent_name": "LLMMissionAgent",
                                    "summary": "ok", "failed": False,
                                    "findings": [{"value": evidence_value,
                                                 "source": "UN Comtrade",
                                                 "confidence": 0.8,
                                                 "note": note,
                                                 "retrieved_at": "2026-07-20",
                                                 "status": ""}]}},
        "report": {"text": report_text},
    }


def test_master_prompt_a3_example_reproduced_17k_vs_11_88m_fails():
    """إعادة إنتاج مثال المواصفة حرفياً: 17K$ في المتن مقابل 11.88 مليون$
    في سجل الأدلة — تناقضٌ حقيقي بلا تفسير => بند فشل غير قابل للإصلاح."""
    from silk_quality_gate import _check_evidence_body_numeric_consistency
    dr = _dr("## 3. نظرة عامة على السوق وحجمه\n"
             "واردات المنتج نحو 17000 دولار في آخر سنة مرصودة.",
             evidence_value=11_880_000, note="واردات 2023 (UN Comtrade)")
    findings = _check_evidence_body_numeric_consistency(dr)
    assert findings, "التناقض 17K$/11.88M$ لم يُلتَقط"
    assert findings[0]["check"] == "evidence_body_numeric_contradiction"
    assert findings[0]["repairable"] is False


def test_master_prompt_a3_example_fails_the_full_quality_gate():
    from silk_quality_gate import run_quality_gate, FAIL
    dr = _dr("## 3. نظرة عامة على السوق وحجمه\n"
             "## 1. الخلاصة التنفيذية\n"
             "واردات المنتج نحو 17000 دولار في آخر سنة مرصودة.\n"
             "## 2. منهجية البحث ونطاقه\nملاحظات.",
             evidence_value=11_880_000)
    out = run_quality_gate({"deep_research": dr})
    assert out["verdict"] == FAIL
    assert any(f["check"] == "evidence_body_numeric_contradiction"
              for f in out["findings"])


def test_agreeing_numbers_across_evidence_and_body_raise_nothing():
    from silk_quality_gate import _check_evidence_body_numeric_consistency
    dr = _dr("واردات السوق نحو 9 مليون دولار في آخر سنة مرصودة.",
             evidence_value=9_000_000)
    assert _check_evidence_body_numeric_consistency(dr) == []


def test_growth_rate_finding_not_conflated_with_absolute_dollar_amount():
    """مراجعة الشيفرة: حقيقة **نسبة نمو** («نمو الواردات 9% سنوياً»، قيمتها
    الخام 9 تعني نسبةً لا مبلغاً) تذكر لفظ «واردات» أيضاً — لا يجوز مقارنتها
    برقمٍ دولاريّ في المتن (62 مليون$) كأنها القيمة المطلقة نفسها؛ نسبة
    62,000,000/9 زائفة تماماً ولا تعني تناقضاً حقيقياً."""
    from silk_quality_gate import _check_evidence_body_numeric_consistency
    dr = _dr("الواردات نحو 62 مليون دولار في آخر سنة مرصودة.",
             evidence_value=9, note="نمو الواردات 9% سنوياً")
    assert _check_evidence_body_numeric_consistency(dr) == []


def test_explained_contradiction_in_local_window_does_not_fire():
    """تناقضٌ حقيقي لكن مُفسَّرٌ صراحةً ضمن نافذته المحلية (٦٠ محرفاً) —
    عقد عدم الاختلاق يحفظ الرقمين ويُفسِّر لا يُصلِح صامتاً، فلا يُعامَل هذا
    التفسير كفشل تسليمٍ صارخ."""
    from silk_quality_gate import _check_evidence_body_numeric_consistency
    dr = _dr("واردات السوق نحو 17000 دولار — مؤشر سياقي لفئة كومتريد مجاورة، "
             "لا يُصلَح برقمٍ مختلَق.", evidence_value=11_880_000)
    assert _check_evidence_body_numeric_consistency(dr) == []


def test_kuwait_canonical_fixture_does_not_fire_new_check(monkeypatch):
    """المدوّنة القانونية (زبدة الفول السوداني/الكويت) تحمل تناقض سعرٍ آخر
    (تجزئة/جملة) مُفسَّراً بفحصٍ منفصل بالفعل — الفحص الجديد (مقيَّد بلفظ
    «واردات») لا يُطلق شيئاً هنا (لا علمٌ مزدوج على نفس الحادثة)."""
    import silk_render as R
    from silk_quality_gate import _check_evidence_body_numeric_consistency
    dr = R.build_view(kuwait_research_blob())["deep_research"]
    assert _check_evidence_body_numeric_consistency(dr) == []


def test_kuwait_canonical_fixture_quality_gate_unaffected():
    """الحكم الكلي لبوابة الجودة على مدوّنة الكويت يبقى كما كان (الفحص
    الجديد لا يُدخِل أيّ بند على هذا الشكل)."""
    import silk_render as R
    import silk_quality_gate as QG
    view = R.build_view(kuwait_research_blob())
    out = QG.run_quality_gate(view)
    assert not any(f["check"] == "evidence_body_numeric_contradiction"
                  for f in out["findings"])

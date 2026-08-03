"""Master Prompt Part 2 §F — بطارية المقاييس المرجعية (٣ حالات معاً).

ثلاث حالاتٍ من أقاليم/عائلات منتجٍ مختلفة تُثبِت أن بوّابات القسم (أ-د) —
تصنيف HS، اتساق الحكم، اتساق الأرقام، تغطية المصادر — عامّةٌ لا مُخصَّصةٌ
لسوقٍ بعينه:

  ١) زبدة الفول السوداني × الكويت (`tools/canonical_kuwait_peanut_butter.py`)
     — الحالة الأصلية (رمزٌ **خطأ** مُتعمَّد 040510 يجب أن يُرفَض/يُعاد تأطيره).
  ٢) تمور × ألمانيا (`tools/canonical_germany_dates.py`) — إطار الاتحاد
     الأوروبي/TARIC، رمزٌ **صحيح** 080410.
  ٣) عسل × اليابان (`tools/canonical_japan_honey.py`) — إقليم شرق آسيا،
     رمزٌ **صحيح** 040900.

كل حالةٍ تُفحَص عبر نفس البوّابات الأربع معاً: رمز HS (تحقّق/رفض حسب
الحالة)، اتساق الحكم عند التسليم (§B)، صفر تناقضٍ رقمي داخلي (§A3/§C)،
تغطية مصادر ≥٨٥٪ (§D)، وبنية الأقسام الأحد عشر (§E).

Run: python3 -m pytest tests/test_benchmark_battery_part2.py -q
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from tools.canonical_kuwait_peanut_butter import (  # noqa: E402
    KUWAIT_PRODUCT, KUWAIT_WRONG_HS, kuwait_research_blob)
from tools.canonical_germany_dates import (  # noqa: E402
    GERMANY_PRODUCT, GERMANY_HS, germany_dates_research_blob)
from tools.canonical_japan_honey import (  # noqa: E402
    JAPAN_PRODUCT, JAPAN_HS, japan_honey_research_blob)

_CORRECT_CASES = (
    ("Germany/dates", GERMANY_PRODUCT, GERMANY_HS, germany_dates_research_blob),
    ("Japan/honey", JAPAN_PRODUCT, JAPAN_HS, japan_honey_research_blob),
)
_ALL_CASES = _CORRECT_CASES + (
    ("Kuwait/peanut_butter", KUWAIT_PRODUCT, KUWAIT_WRONG_HS, kuwait_research_blob),)


# ═══════════════════ §A — رمز HS: تحقّق للصحيح، رفض للخطأ ═══════════════════

@pytest.mark.parametrize("label,product,hs,_blob", _CORRECT_CASES)
def test_battery_a_correct_hs_confirmed(label, product, hs, _blob):
    from silk_hs_confirm import confirm_hs
    from silk_hs_resolver import chapter_valid
    assert chapter_valid(hs), f"{label}: {hs} فصلٌ غير صالح"
    out = confirm_hs(product, hs)
    assert out["confirmed"] is True, f"{label}: {hs} لم يُؤكَّد — {out}"


def test_battery_a_kuwait_wrong_hs_rejected():
    """الحالة الأصلية: 040510 (زبدة/ألبان) لا يُؤكَّد لمنتج «زبدة الفول
    السوداني» — الصفة المميّزة (فول سوداني) غائبة عن وصف الرمز."""
    from silk_hs_confirm import confirm_hs
    out = confirm_hs(KUWAIT_PRODUCT, KUWAIT_WRONG_HS)
    assert out["confirmed"] is False


# ═══════════════════ §B — اتساق الحكم عند التسليم (docx فعلي) ═══════════════════

@pytest.mark.parametrize("label,product,hs,blob_fn", _ALL_CASES)
def test_battery_b_verdict_consistent_in_rendered_docx(label, product, hs,
                                                        blob_fn, monkeypatch):
    pytest.importorskip("docx")
    from silk_render import build_view
    from silk_reports import render_docx, render_client_docx
    monkeypatch.setenv("SILK_HERMETIC", "1")
    view = build_view(blob_fn())
    tmp = tempfile.mkdtemp()
    render_docx(view, os.path.join(tmp, "research.docx"))       # لا تناقض
    render_client_docx(view, os.path.join(tmp, "client.docx"))  # لا تناقض


# ═══════════════ §C — صفر تناقضٍ رقمي داخلي (سجل الأدلة/المتن) ═══════════════

@pytest.mark.parametrize("label,product,hs,blob_fn", _ALL_CASES)
def test_battery_c_zero_unreconciled_numeric_contradiction(label, product, hs,
                                                            blob_fn):
    import silk_render as R
    from silk_quality_gate import _check_evidence_body_numeric_consistency
    dr = R.build_view(blob_fn())["deep_research"]
    findings = _check_evidence_body_numeric_consistency(dr)
    assert findings == [], f"{label}: تناقضٌ رقميّ غير مُفسَّر — {findings}"


# ═══════════════════════ §D — تغطية مصادر ≥٨٥٪ ═══════════════════════

@pytest.mark.parametrize("label,product,hs,blob_fn", _ALL_CASES)
def test_battery_d_source_coverage_meets_threshold(label, product, hs, blob_fn):
    import silk_render as R
    from silk_source_coverage import compute_source_coverage, SOURCE_COVERAGE_MIN_PCT
    dr = R.build_view(blob_fn())["deep_research"]
    cov = compute_source_coverage(dr)
    assert cov["pct"] >= SOURCE_COVERAGE_MIN_PCT, f"{label}: {cov}"


# ═══════════════════ §E — بنية الأقسام الأحد عشر ═══════════════════

@pytest.mark.parametrize("label,product,hs,blob_fn", _ALL_CASES)
def test_battery_e_section_structure_passes(label, product, hs, blob_fn):
    import silk_render as R
    from silk_quality_gate import _check_section_structure
    dr = R.build_view(blob_fn())["deep_research"]
    assert _check_section_structure(dr) == [], label


# ═════════ مراسي السلامة الرقمية (Master Prompt Part 2 §F، البند ١٤-١٥) ═════════
# كل حالةٍ صحيحة تحمل ٢-٣ أرقاماً مرجعية صريحة يُتحقَّق من ظهورها حرفياً في
# متن التقرير المبنيّ — انحرافٌ جسيمٌ عنها (لا رمز HS، ولا حكمٌ آخر) يُفشِل.
# الكويت (زبدة الفول السوداني) مراسيها مغطّاة أصلاً في
# test_golden_deep_research_contract.py (HHI 2900، تناقض السعر 0.67$/6$).

def _flat(text: str) -> str:
    """طبّع الفراغات (بما فيها التفاف الأسطر من نصّ المصدر) لمطابقةٍ لا
    تتأثّر بموضع كسر السطر — نفس المضمون سواء التفّ أم لا."""
    return " ".join(text.split())


def test_battery_f_germany_dates_numeric_sanity_anchors():
    """مراسي ألمانيا: واردات ~38 مليون دولار، HHI 780، وإفصاح MFN الصادق
    (لا أفضلية سعودية-أوروبية) — إطار TARIC صراحةً."""
    import silk_render as R
    dr = R.build_view(germany_dates_research_blob())["deep_research"]
    text = _flat(dr["report"]["text"])
    assert "38 مليون دولار" in text
    assert "780" in text
    assert "TARIC" in text
    assert "لا اتفاقية تجارة تفضيلية بين السعودية والاتحاد الأوروبي" in text


def test_battery_f_japan_honey_numeric_sanity_anchors():
    """مراسي اليابان: واردات ~62 مليون دولار، HHI 1450، وإفصاح صادق (لا
    اتفاقية شراكة اقتصادية سعودية-يابانية) — إطار الحجر الزراعي/JAS صراحةً."""
    import silk_render as R
    dr = R.build_view(japan_honey_research_blob())["deep_research"]
    text = _flat(dr["report"]["text"])
    assert "62 مليون دولار" in text
    assert "1450" in text
    assert "الحجر الزراعي" in text
    assert "لا اتفاقية تجارة تفضيلية أو شراكة اقتصادية بين السعودية واليابان" in text


# ═══════════ تكامل: بوّابة الجودة الكاملة تعمل على الحالات الثلاث ═══════════

@pytest.mark.parametrize("label,product,hs,blob_fn", _ALL_CASES)
def test_battery_quality_gate_runs_on_all_three_shapes(label, product, hs, blob_fn):
    import silk_render as R
    import silk_quality_gate as QG
    view = R.build_view(blob_fn())
    out = QG.run_quality_gate(view)
    assert "verdict" in out and "findings" in out, label
    # لا بند تناقضٍ رقمي ولا تغطية مصادرٍ ناقصة على أيٍّ من الحالات الثلاث —
    # الحالة الوحيدة المسموح لها ببندٍ (hs_flagged/إعادة تأطير) هي الكويت،
    # وذاك يُغطّى باختباراتٍ مخصّصة في test_golden_deep_research_contract.py.
    assert not any(f["check"] in ("evidence_body_numeric_contradiction",
                                  "source_coverage_below_threshold")
                  for f in out["findings"]), (label, out["findings"])

"""البند هـ — فرض البنية الفرعية لأقسام التقرير · E narrative sub-structure.

طلب المالك (Issue #144، البند هـ): أُقفِلت العناوين الأحد عشر وترتيبها فقط
(`_section_order_issues`)؛ البنية الفرعية داخل القسم غير مفحوصة — قسمٌ بعنوانٍ
صحيح قد يخلو من العناصر التي يطلبها موجّه الكاتب.

هذا الحارس (`_section_substructure_issues`) **غير حاجب (WARN)**، مقيَّدٌ بنافذة
قسم التوصيات (الدرس ٤٢)، ومكمّلٌ مستقلّ لطلب المراجع النثري. النطاق: المجموعة
١-٣ من المذكّرة `docs/DESIGN_E_SECTION_SUBSTRUCTURE.md` — العناصر التي يطلبها
الموجّه أصلاً (§6.1: خارطة ٩٠ يومًا + شرطا قلب الحكم للحكم المشروط). إضافةُ
عناصرَ جديدةٍ للموجّه مؤجّلةٌ لقياسٍ حيّ (المذكّرة §٥).
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_ai_judge as j  # noqa: E402


_RECS = "## 10. التوصيات الاستراتيجية\n"
_APPENDIX = "\n## 11. الملاحق\nلا شيء."


def _report(recs_body: str, verdict_line: str = "التوصية: دخول مشروط.") -> str:
    return ("## 1. الخلاصة التنفيذية\n" + verdict_line + "\n"
            + _RECS + recs_body + _APPENDIX)


# ═══════════════ ١) الدالة الأساسية ═══════════════

def test_conditional_verdict_with_full_substructure_passes():
    draft = _report("### شرطا قلب الحكم\nشرط أول؛ شرط ثانٍ.\n"
                    "### خارطة طريق الدخول (٩٠ يومًا)\nخطوة بمسؤول.")
    assert j._section_substructure_issues(draft) == []


def test_conditional_verdict_missing_both_flags_two_issues():
    draft = _report("نصٌّ عامٌّ بلا بنيةٍ فرعية.")
    issues = j._section_substructure_issues(draft)
    assert len(issues) == 2
    assert any("خارطة" in i for i in issues)
    assert any("قلب الحكم" in i for i in issues)


def test_go_verdict_does_not_require_flip_conditions():
    """حكم GO (لا مشروط/مراقبة) => «شرطا قلب الحكم» غير مطلوبٍ؛ الخارطة كافية."""
    draft = _report("### خارطة طريق الدخول (٩٠ يومًا)\nخطوات.",
                    verdict_line="التوصية: الدخول (GO).")
    assert j._section_substructure_issues(draft) == []


def test_missing_recommendations_section_is_silent_here():
    """القسم غائبٌ أصلًا => يبلّغه `_section_order_issues` لا هذا الحارس."""
    assert j._section_substructure_issues("## 1. الخلاصة التنفيذية\nنص") == []


def test_window_scoped_flip_in_another_section_does_not_count():
    """«شرطا قلب الحكم» في قسمٍ آخر لا يُحتسَب — الفحص على نافذة التوصيات فقط."""
    draft = ("## 1. الخلاصة التنفيذية\nالتوصية: دخول مشروط. شرطا قلب الحكم مذكوران هنا خطأً.\n"
             + _RECS + "### خارطة طريق الدخول (٩٠ يومًا)\nخطوات.\n" + _APPENDIX)
    issues = j._section_substructure_issues(draft)
    assert any("قلب الحكم" in i for i in issues)  # غائبٌ عن نافذة التوصيات


# ═══════════════ ٢) نافذة القسم ═══════════════

def test_section_window_extracts_only_its_own_span():
    draft = ("## 9. تقييم المخاطر\nمخاطر.\n"
             "## 10. التوصيات الاستراتيجية\nمحتوى التوصيات.\n"
             "## 11. الملاحق\nملاحق.")
    win = j._section_window(draft, "التوصيات الاستراتيجية")
    assert "محتوى التوصيات" in win
    assert "مخاطر" not in win and "ملاحق" not in win


def test_section_window_absent_title_returns_none():
    assert j._section_window("## 1. الخلاصة التنفيذية\nنص", "التوصيات الاستراتيجية") is None


# ═══════════════ ٣) الوصل في review_report — غير حاجب ═══════════════

def _valve_on():
    return mock.patch.dict(os.environ, {"SILK_E_SUBSTRUCTURE_CHECK": "1"})


def test_substructure_issues_surface_as_nonblocking_in_review():
    """الصمّام مفعّل + مسار الاحتياط (لا ردّ نموذج): مشاكل البنية الفرعية تظهر
    ضمن issues (تُعلَن في «حدود التقرير») لكن **ليست** ضمن blocking."""
    draft = _report("نصٌّ عامٌّ بلا خارطةٍ ولا شرطَي قلب.")
    with _valve_on(), mock.patch.object(j, "available", return_value=True), \
         mock.patch.object(j, "_call", return_value=None):  # يفشل النداء => احتياط
        out = j.review_report(draft, {"m": {"findings": []}})
    assert out is not None
    joined = " | ".join(out["issues"])
    assert "البند هـ" in joined                     # ظهرت في issues
    assert not any("البند هـ" in b for b in out["blocking"])  # غير حاجبة


def test_full_substructure_adds_no_review_noise():
    """الصمّام مفعّل + تقريرٌ كامل البنية => لا مشاكل بند هـ (لا تحذيرٌ كاذب)."""
    draft = _report("### شرطا قلب الحكم\nشرط.\n"
                    "### خارطة طريق الدخول (٩٠ يومًا)\nخطوة.")
    with _valve_on(), mock.patch.object(j, "available", return_value=True), \
         mock.patch.object(j, "_call", return_value=None):
        out = j.review_report(draft, {"m": {"findings": []}})
    if out is not None:
        assert not any("البند هـ" in i for i in out["issues"])


def test_valve_off_by_default_never_adds_substructure_issues():
    """الصمّام مطفأ (افتراضي) => لا مشاكل بند هـ في المراجعة إطلاقًا (السلوك
    كاليوم؛ يمنع التحذير الكاذب حتى معايرة المالك الحيّة)."""
    draft = _report("نصٌّ عامٌّ بلا خارطةٍ ولا شرطَي قلب.")
    with mock.patch.dict(os.environ, {"SILK_E_SUBSTRUCTURE_CHECK": "0"}), \
         mock.patch.object(j, "available", return_value=True), \
         mock.patch.object(j, "_call", return_value=None):
        out = j.review_report(draft, {"m": {"findings": []}})
    if out is not None:
        assert not any("البند هـ" in i for i in out["issues"])

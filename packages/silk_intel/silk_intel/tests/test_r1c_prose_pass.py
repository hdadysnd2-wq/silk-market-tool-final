"""اختبارات PR-C0 (تمرير النثر R1): حارس ضد ارتداد الصياغة الحرفية.

المشكلة المرصودة في المراجعة: مفاهيم إنجليزية تقنية تُترجَم حرفياً بدل
التعبير عنها بلغة الأعمال الخليجية. هذه الاختبارات تثبّت الإصلاحات الخمسة
المؤكَّدة (+ اكتساح القالب) في طبقتها الصحيحة وتمنع عودتها:

  الصياغة الخاطئة (ممنوعة)          →  البديل المعتمَد
  ─────────────────────────────────────────────────────────
  «مطبَّع لكل كيلوغرام»              →  «محسوب بسعر الكيلوغرام الواحد …»
  عمود «الدليل» المتسرّب (markdown قديم)  →  «التوثيق» (محايد، لا رُتبة — WS10)
  «سعر جملة مرجعي (كومتريد)»        →  «متوسط سعر الاستيراد الرسمي (UN Comtrade)»
  «تكلفة هبوط»                      →  «التكلفة الواصلة»
  «طريقة الاشتقاق»                  →  «طريقة الحساب»

الطبقات الثلاث: (أ) المصدر (بعثة/كاتب) ينتج اللغة الصحيحة، (ب) شبكة أمان
في مُطهِّر تصدير العميل تلتقط أيّ مخرَج حيّ/مخزَّن قديم، (ج) العيّنة المحفوظة
تُظهر الصياغة الصحيحة ولا تحمل أيّاً من الصيغ الخاطئة.
Run:  python3 -m pytest tests/test_r1c_prose_pass.py -q
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import docx_all_text  # noqa: E402


# الصيغ الخاطئة التي يجب ألّا تظهر في متن العميل مطلقاً (استُثنيت «الدليل»
# المجرّدة لأنها مشروعة في «قوة الدليل» بالملحق — الممنوع هو عمود الجدول).
_FORBIDDEN_PHRASINGS = (
    "سعر جملة مرجعي", "كومتريد", "تكلفة هبوط", "طريقة الاشتقاق",
)


# ── (أ) طبقة المصدر: البعثة والكاتب ينتجان لغة الأعمال ────────────────────

def test_pricing_scout_label_is_business_idiom_not_calque():
    """وسم سطر كومتريد المرجعي: لا تعريب لاسم مصدر، ولا «سعر جملة مرجعي»
    الحرفية — بل «متوسط سعر الاستيراد الرسمي (UN Comtrade)»."""
    import silk_missions as M
    ins = M.MISSIONS["pricing_scout"]["instructions"]
    assert "متوسط سعر الاستيراد الرسمي" in ins
    assert "UN Comtrade" in ins
    assert "سعر جملة مرجعي" not in ins
    assert "كومتريد" not in ins


def test_writer_prompt_competing_table_has_no_documentation_level_column():
    """WS10 (قرار المالك): عمود «مستوى التوثيق» أُزيل من جدول المنتجات المنافسة
    (لا عمود إسناد في المتن)، والسعر يبقى «محسوباً بسعر الكيلوغرام … للمقارنة
    العادلة» لا «مطبَّعاً»."""
    import silk_ai_judge as J
    src = inspect.getsource(J.deep_report)
    assert "مستوى التوثيق" not in src
    assert "بسعر الكيلوغرام" in src and "للمقارنة العادلة" in src
    # لا كلمة هندسية «مطبَّع» في عقد الكاتب (تُطبَّع لغوياً لا رقمياً).
    assert "مُطبَّع" not in src and "مطبَّع" not in src


def test_writer_prompt_tam_sam_som_column_is_calculation_method():
    """عمود جدول TAM/SAM/SOM: «طريقة الحساب» لا «طريقة الاشتقاق» الأكاديمية."""
    import silk_ai_judge as J
    src = inspect.getsource(J.deep_report)
    assert "طريقة الحساب" in src
    assert "طريقة الاشتقاق" not in src


# ── (ب) شبكة الأمان: مُطهِّر تصدير العميل يعيد صياغة أيّ صيغة حرفية ─────────

def test_client_sanitize_rewrites_every_calque():
    import silk_reports as R
    pairs = [
        ("سعر جملة مرجعي (كومتريد، متوسط)",
         "متوسط سعر الاستيراد الرسمي", "UN Comtrade"),
        ("يعطي تكلفة هبوط 9.8$/كغم", "التكلفة الواصلة", None),
        ("| المتجر وتاريخ الرصد | الدليل |", "| التوثيق |", None),
        ("بأسعارها مطبَّعةً لكل كيلوغرام بالدولار",
         "محسوبةً بسعر الكيلوغرام الواحد", None),
    ]
    for raw, must_have, must_have2 in pairs:
        out = R._client_sanitize(raw)
        assert must_have in out, f"{raw!r} → {out!r}"
        if must_have2:
            assert must_have2 in out, f"{raw!r} → {out!r}"
    # لا تعريب لاسم المصدر بعد التطهير.
    assert "كومتريد" not in R._client_sanitize("متوسط كومتريد للواردات")
    assert "تكلفة هبوط" not in R._client_sanitize("تكلفة هبوط عند الحدود")


# ── (ج) العيّنة المحفوظة تُظهر اللغة الصحيحة ولا تحمل أيّ صيغة خاطئة ────────

def _client_sample_text() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "samples", "client_report_latest.docx")
    assert os.path.exists(path), "شغّل tools/gen_client_report_sample.py"
    return docx_all_text(path)


def test_committed_client_sample_uses_business_idiom():
    text = _client_sample_text()
    for good in ("متوسط سعر الاستيراد الرسمي",
                 "بسعر الكيلوغرام الواحد", "طريقة الحساب"):
        assert good in text, f"مفقود من العيّنة: {good}"
    # WS10 (قرار المالك): متن العميل نظيف — لا عمود «مستوى التوثيق» ولا شارات
    # قوة دليل ولا عمود مصدر لكل صف؛ الإسناد في قسم المراجع وحده.
    for bad in ("مستوى التوثيق", "قوة الدليل", "✓ موثّق", "◐ ثانوي", "○ غير"):
        assert bad not in text, f"شارة/عمود إسناد عاد للعيّنة: {bad}"


def test_committed_client_sample_has_no_calque_phrasings():
    text = _client_sample_text()
    hits = [p for p in _FORBIDDEN_PHRASINGS if p in text]
    assert hits == [], f"صيغ حرفية عادت للعيّنة: {hits}"
    # جملة المنهجية «… يُعلَن … بدل حذفه» لم تعُد في متن المنافسة للعميل.
    assert "بدل حذفه" not in text

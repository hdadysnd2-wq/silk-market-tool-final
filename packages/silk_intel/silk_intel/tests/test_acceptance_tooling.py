"""اختبارات أداة القبول (tools/acceptance_run.py) — الدوال النقية فقط
(استخراج نص docx + مسح المصطلحات المحظورة)، هرمِتية بلا شبكة.

يربط الأداة بالعيّنة النظيفة المحفوظة: عيّنة العميل يجب أن تُمسَح نظيفةً،
وأي نص يحوي صيغة حرفية يجب أن يُرصَد — فتصير الأداة نفسها حارس ارتداد.
Run:  python3 -m pytest tests/test_acceptance_tooling.py -q
"""
import importlib.util
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# استيراد السكربت كوحدة (اسم بشرطة لا يُستورَد بـimport عادي).
_spec = importlib.util.spec_from_file_location(
    "acceptance_run", os.path.join(_ROOT, "tools", "acceptance_run.py"))
AR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(AR)


def test_scan_forbidden_catches_each_calque():
    for phrase in ("سعر جملة مرجعي (كومتريد)", "تكلفة هبوط عند الحدود",
                   "طريقة الاشتقاق", "بأسعارها مطبَّعةً لكل كيلوغرام"):
        assert AR.scan_forbidden(phrase), f"لم يُرصَد: {phrase}"


def test_scan_forbidden_catches_telemetry():
    assert AR.scan_forbidden("نجحت 11 بعثة من 12")           # mission/successful
    assert AR.scan_forbidden("comtrade_imports")             # tool name
    assert AR.scan_forbidden("verdict: GO")                  # algorithm language


def test_scan_forbidden_clean_business_prose_passes():
    clean = ("محسوبةً بسعر الكيلوغرام الواحد للمقارنة العادلة، ومستوى التوثيق "
             "لكل صف، ومتوسط سعر الاستيراد الرسمي (UN Comtrade) والتكلفة الواصلة "
             "وطريقة الحساب.")
    assert AR.scan_forbidden(clean) == []


def test_committed_client_sample_scans_clean_via_tool():
    """عيّنة العميل النظيفة تُمسَح خاليةً بأداة القبول نفسها — استخراج docx
    عبر stdlib (بلا python-docx) + المسح."""
    path = os.path.join(_ROOT, "samples", "client_report_latest.docx")
    assert os.path.exists(path), "شغّل tools/gen_client_report_sample.py"
    text = AR.extract_docx_text(path)
    assert "المنتجات المنافسة" in text        # استُخرِج نص فعلي
    assert AR.scan_forbidden(text) == []       # لا مصطلح محظور

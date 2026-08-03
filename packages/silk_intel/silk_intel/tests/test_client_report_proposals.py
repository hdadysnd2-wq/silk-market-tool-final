"""اختبارات مقترحات قالب تقرير العميل (المعتمَدة من المالك):
- ١) تصنيف الاشتراطات ثلاث طبقات (إلزامية/إضافية/نيش) — أسلوب CBI.
- ٢) القناة الأولى الموصى بها للمصدّر الجديد.
- ٤) وعي فئة المنتج من فصل HS (غذاء/صناعي/استهلاكي) — المنصّة تخدم كل
     المنتجات لا الغذاء وحده.
- ٣) ربط الاتجاهات بالفرص + كتلة «نصائح للمصدّر».
Run:  python3 -m pytest tests/ -q
"""
import inspect
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import docx_all_text  # noqa: E402


# ── المقترح ٤: مصنِّف فئة المنتج من فصل HS ────────────────────────────────

def test_hs_category_mapper_covers_food_industrial_consumer():
    import silk_ai_judge as J
    assert J._product_category("080410")[0] == "منتج غذائي/زراعي"      # تمور
    assert J._product_category("620822")[0] == "منسوجات/ملابس/أحذية"    # ملابس
    assert J._product_category("850760")[0] == "آلات/معدّات كهربائية"   # كهربائي
    assert J._product_category("870380")[0] == "مركبات/معدّات نقل"       # مركبة
    assert J._product_category("940360")[0] == "أثاث/ألعاب/سلع استهلاكية"


def test_hs_category_mapper_never_guesses_unmapped():
    import silk_ai_judge as J
    assert J._product_category(None) is None
    assert J._product_category("") is None
    assert J._product_category("990000") is None   # فصل غير مصنَّف
    assert J._product_category("x") is None


def test_writer_injects_product_category_emphasis_when_hs_given():
    """المقترح ٤: عند تمرير hs_code، يُحقَن سطر فئة المنتج وتركيز الاشتراطات
    في برومبت الكاتب — فئة غذائية تذكر سلامة الغذاء، لا اشتراطات فئة أخرى."""
    import silk_ai_judge as J
    captured = {}

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        captured["user"] = user
        return "## 1. الخلاصة التنفيذية\nنص.\n"

    with patch.object(J, "available", lambda: True), \
         patch.object(J, "_call", side_effect=fake_call):
        J.deep_report({}, "ملخّص", {"verdict": "GO"}, "تمور", "هولندا",
                      hs_code="080410")
    assert "فئة المنتج (من فصل HS): منتج غذائي/زراعي" in captured["user"]
    assert "سلامة الغذاء" in captured["user"]

    # منتج صناعي → تركيز مختلف (CE)، لا سلامة غذائية
    with patch.object(J, "available", lambda: True), \
         patch.object(J, "_call", side_effect=fake_call):
        J.deep_report({}, "ملخّص", {"verdict": "GO"}, "بطاريات", "ألمانيا",
                      hs_code="850760")
    assert "آلات/معدّات كهربائية" in captured["user"]
    assert "علامة CE" in captured["user"]


def test_writer_no_category_line_when_hs_unmapped():
    import silk_ai_judge as J
    captured = {}

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        captured["user"] = user
        return "## 1. الخلاصة التنفيذية\nنص.\n"

    with patch.object(J, "available", lambda: True), \
         patch.object(J, "_call", side_effect=fake_call):
        J.deep_report({}, "ملخّص", {"verdict": "GO"}, "منتج", "سوق",
                      hs_code=None)
    assert "فئة المنتج (من فصل HS)" not in captured["user"]


# ── المقترحات ١+٢+٣: عقود برومبت الكاتب ───────────────────────────────────

def test_writer_prompt_requires_requirements_tier_split():
    import silk_ai_judge
    src = inspect.getsource(silk_ai_judge.deep_report)
    assert "ثلاث طبقات" in src
    assert "اشتراطات إلزامية" in src
    assert "يطلبها المشترون" in src
    assert "نيش" in src


def test_writer_prompt_requires_recommended_first_channel():
    import silk_ai_judge
    src = inspect.getsource(silk_ai_judge.deep_report)
    assert "القناة الأولى الموصى بها" in src


def test_writer_prompt_requires_trends_to_opportunity_and_tips():
    import silk_ai_judge
    src = inspect.getsource(silk_ai_judge.deep_report)
    assert "اربط كل" in src and "فرصة تجارية" in src        # اتجاه → فرصة
    assert "نصائح عملية للمصدّر" in src                       # كتلة النصائح


# ── العيّنة المحفوظة تُظهر المقترحات، وتبقى خالية من التِلِمِتري ──────────────

def test_committed_client_sample_demonstrates_proposals():
    import silk_reports as R
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "samples", "client_report_latest.docx")
    assert os.path.exists(path), "شغّل tools/gen_client_report_sample.py"
    text = docx_all_text(path)
    # ١) طبقات الاشتراطات الثلاث
    assert "اشتراطات إلزامية" in text
    assert "اشتراطات إضافية" in text
    assert "أسواق متخصصة" in text
    # ٢) القناة الأولى الموصى بها
    assert "القناة الأولى" in text and "موزّع الأغذية المتخصص" in text
    # ٣) كتلة النصائح
    assert "نصائح عملية للمصدّر" in text
    # يبقى خالياً من التِلِمِتري رغم المقترحات
    assert R._client_forbidden_hits(text) == []

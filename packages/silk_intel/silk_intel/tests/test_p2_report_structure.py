"""اختبار الهيكل الـ14 (P2-7) + وجه بلا شعارات (5b) — the 14-section lock.

يقفل: (١) ترتيب الأقسام المرقّمة الأربعة عشر كما في مواصفة المالك؛
(٢) وجه docx خالٍ من شعارات النزاهة وصياح INSUFFICIENT DATA ورموز
الآلة؛ (٣) شفافية 2B (المصادر المُحاوَلة) باقية في ملحق المحلّل.
Run:  python3 -m pytest tests/test_p2_report_structure.py -q
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network, docx_all_text  # noqa: E402

import silk_store  # noqa: E402

SECTIONS = ["١. الخلاصة التنفيذية", "٢. منهجية البحث",
            "٣. تعريف السوق ونطاقه", "٤. نظرة عامة على السوق",
            "٥. ديناميكيات السوق", "٦. حجم السوق والتوقعات",
            "٧. تحليل التقسيم", "٨. تحليل التجارة (استيراد/تصدير)",
            "٩. الأسواق المرشّحة الأخرى", "١٠. المشهد التنافسي",
            "١١. استخبارات العميل والطلب", "١٢. المشهد التنظيمي والمخاطر",
            "١٣. الاتجاهات والتوقع المستقبلي", "حدود هذا التقرير",
            "١٤. التوصيات الاستراتيجية", "الملحق: تغطية المصادر وأثرها"]


def _docx_path():
    pytest.importorskip("docx")
    import silk_engine
    from silk_render import build_view
    from silk_reports import render_docx
    silk_store.migrate()
    silk_store.upsert_trade_flows([
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2021, "flow": "M", "value_usd": 4.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 6.0e7, "qty_kg": 2.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 1.8e7, "qty_kg": 8.0e6},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "IRN",
         "year": 2023, "flow": "M", "value_usd": 3.0e7}])
    with block_network():
        res = silk_engine.analyze(
            "تمور", countries=[{"iso3": "CHN", "m49": "156"}], year=2023,
            with_research=True, with_requirements=True, with_risk=True)
    return render_docx(build_view(res),
                       os.path.join(tempfile.mkdtemp(), "r14.docx"))


def test_fourteen_sections_in_order():
    from docx import Document
    path = _docx_path()
    texts = [p.text for p in Document(path).paragraphs]
    idx = []
    for sec in SECTIONS:
        assert sec in texts, sec
        idx.append(texts.index(sec))
    assert idx == sorted(idx), "sections out of order"
    # الحدود قبل التوصيات (§10.3) مضمونة بترتيب القائمة أعلاه.


def test_report_face_is_slogan_free_and_machine_free():
    path = _docx_path()
    joined = docx_all_text(path)
    for banned in ("لا اختلاق", "لا مخمّنة", "الفجوات معلنة",
                   "INSUFFICIENT DATA", "قرار أوّلي لا نهائي",
                   "لا بند مرصوداً", "CONDITIONAL-GO (ثقة"):
        assert banned not in joined, banned
    # شفافية 2B باقية في ملحق المحلّل — لا على وجه الأقسام.
    if "بيانات غير كافية لقسم" in joined:
        assert "أقسام دون عتبة الكفاية" in joined
    # سطر المصدر تحت الأرقام هو إشارة النزاهة — حاضر.
    assert "المصدر: " in joined or "المصدر:" in joined
    # السيناريوهات (١٣): مشتقة من المدى المرصود حين يتوافر خط اتجاه،
    # وإلا غياب معلن هادئ — كلاهما مقبول، لا توقع مخترع أبداً.
    assert ("المدى التاريخي المرصود" in joined
            or "بيانات الاتجاه غير كافية" in joined)

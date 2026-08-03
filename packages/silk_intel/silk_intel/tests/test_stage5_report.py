"""اختبارات Stage 5 — التقرير الكامل (docx + Markdown) والواجهة من القالب الواحد.

يقفل: النموذج القانوني يحمل حزمة البحث والقرار ومشتقاتها القاعدية (SWOT/شرائح/
دليل مورّدين)؛ SWOT كل خليته بدليل والفارغ معلن؛ تقرير Markdown كامل بكل رقم
ومصدره؛ docx يتضمن قرار الدخول وTAM/SAM/SOM؛ مسار /report.md محروس؛ والواجهة
تحمل الشاشات ورابط Markdown.
"""
import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

import silk_store  # noqa: E402


def _seed_store():
    silk_store.migrate()
    silk_store.upsert_trade_flows([
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2021, "flow": "M", "value_usd": 4.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2022, "flow": "M", "value_usd": 5.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 6.0e7, "qty_kg": 2.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "IRN",
         "year": 2023, "flow": "M", "value_usd": 3.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 1.8e7, "qty_kg": 8.0e6},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "TUN",
         "year": 2023, "flow": "M", "value_usd": 1.2e7}])


def _analyzed():
    import silk_engine
    with block_network():
        return silk_engine.analyze(
            "تمور", countries=[{"iso3": "CHN", "m49": "156"}], year=2023,
            with_research=True, with_requirements=True, with_risk=True)


def _seed_store_multi():
    """يبذر مورّداً ثانياً (الإمارات) — لاختبار قسم الأسواق المرشّحة الأخرى."""
    _seed_store()
    silk_store.upsert_trade_flows([
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "WLD",
         "year": 2021, "flow": "M", "value_usd": 1.5e7},
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 2.0e7, "qty_kg": 5.0e6},
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 1.4e7, "qty_kg": 4.0e6}])


def _analyzed_multi():
    import silk_engine
    with block_network():
        return silk_engine.analyze(
            "تمور", countries=[{"iso3": "CHN", "m49": "156"},
                              {"iso3": "ARE", "m49": "784"}], year=2023,
            with_research=True, with_requirements=True, with_risk=True)


def test_view_carries_research_decision_and_rule_derived_sections():
    _seed_store()
    from silk_render import build_view
    view = build_view(_analyzed())
    m = view["markets"][0]
    assert m["research"]["schema"] == "silk.research/v1"
    assert m["entry_decision"]["schema"] == "silk.decision/v1"
    # SWOT قاعدي: حصة سعودية مرصودة => خلية قوة بدليل كومتريد.
    s_cells = m["swot"]["S"]
    assert any("حضور سعودي" in c["text"] and "Comtrade" in c["evidence"]
               for c in s_cells)
    # سوق مفتّت (HHI 0.38 ليس <0.15) => لا خلية فرص للتفتت — القاعدة لا تُجامل.
    assert not any("مفتّت" in c["text"] for c in m["swot"]["O"])
    assert m["segments"] and any("الحلال" in s["segment"] or "رمضان" in
                                 s["segment"] for s in m["segments"])
    assert m["supplier_directory"]["note"]


def test_swot_without_research_is_declared_not_invented():
    from silk_render import _swot
    empty = _swot(None)
    assert empty["S"] == [] and empty["W"] == [] and empty["O"] == [] \
        and empty["T"] == []
    assert "with_research" in empty["note"]


def test_render_markdown_full_report_every_number_sourced():
    _seed_store()
    from silk_render import build_view
    from silk_reports import render_markdown
    from silk_narrative import VERDICT_AR
    md = render_markdown(build_view(_analyzed()))
    assert "تمور" in md and "080410" in md
    assert "قرار الدخول" in md                      # قسم §8
    # الحكم يصل مُعرَّباً — لا رمز آلة خام (GO/CONDITIONAL-GO/NO-GO) على
    # وجه التقرير (سدّ تسريب).
    assert any(v in md for v in VERDICT_AR.values())
    for raw in ("GO", "CONDITIONAL-GO", "NO-GO"):
        assert raw not in md
    assert "TAM" in md and "60,000,000" in md.replace("٬", ",")
    assert "UN Comtrade" in md                      # المصدر بجانب الرقم
    assert "مُقدَّر" in md                           # وسم النماذج المعلنة
    assert "SWOT" in md or "سوات" in md
    assert "المورّدين" in md or "الموردين" in md
    assert "أثر المصادر" in md or "provenance" in md.lower()
    assert "بيانات غير كافية" in md                 # بوابة 2B تعمل في MD أيضاً


def test_docx_includes_decision_and_tam_sections():
    pytest.importorskip("docx")
    _seed_store()
    from conftest import docx_all_text
    from silk_render import build_view
    from silk_reports import render_docx
    path = render_docx(build_view(_analyzed()),
                       os.path.join(tempfile.mkdtemp(), "r.docx"))
    texts = docx_all_text(path)  # فقرات + خلايا جداول (بعض الأقسام صارت جداول)
    assert "قرار الدخول" in texts
    assert "TAM" in texts
    assert "SWOT" in texts or "سوات" in texts
    assert "مُقدَّر" in texts


def test_exec_summary_is_narrative_and_methodology_scope_sections_exist():
    """مواصفة تقرير عالمي (بلاغ المالك): الخلاصة سرد بشري لا شروط كودية،
    ومنهجية البحث ونطاق السوق قسمان ظاهران — من حقول محسوبة فعلاً، لا رقم
    جديد ولا ادعاء غير مسنود."""
    pytest.importorskip("docx")
    _seed_store()
    from conftest import docx_all_text
    from silk_render import build_view
    from silk_reports import render_docx, render_markdown
    view = build_view(_analyzed())
    path = render_docx(view, os.path.join(tempfile.mkdtemp(), "r.docx"))
    texts = docx_all_text(path)
    assert "منهجية البحث" in texts and "تعريف السوق ونطاقه" in texts
    assert "التوصية: " in texts                    # سرد لا "القرار: X (ثقة"
    assert "080410" in texts                        # نطاق السوق يذكر رمز HS الفعلي
    assert "بحثاً أولياً" in texts                  # الفجوة النوعية معلنة صراحة
    md = render_markdown(view)
    assert "## منهجية البحث" in md and "## تعريف السوق ونطاقه" in md
    assert "التوصية: " in md


def test_report_md_endpoint_guarded_and_derived_from_template():
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    import importlib
    import api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    os.environ.pop("SILK_API_KEY", None)
    os.environ["SILK_RATE_LIMIT"] = "0"
    client = TestClient(api.create_app())
    _seed_store()
    res = _analyzed()
    with mock.patch("silk_storage.get_analysis", return_value=res):
        r = client.get("/analyses/1/report.md")
    assert r.status_code == 200 and "تمور" in r.text and "قرار الدخول" in r.text
    with mock.patch("silk_storage.get_analysis", return_value=None):
        assert client.get("/analyses/99/report.md").status_code == 404
    os.environ.pop("SILK_RATE_LIMIT", None)


def test_source_lines_never_leak_raw_confidence_decimal():
    """Finding 0 (مراجعة تقرير أرقام منفصلة بلا معنى): _f_src_bare كانت تطبع
    ثقة عشرية خامة (ثقة: 0.9) في كل سطر مصدر داخل حزمة البحث — في كلا
    الصيغتين. يجب أن تُستبدل بصيغة بشرية (عالية/متوسطة/منخفضة)."""
    import re
    _seed_store()
    from silk_render import build_view
    from silk_reports import render_markdown
    md = render_markdown(build_view(_analyzed()))
    assert not re.search(r"ثقة:\s*0\.\d", md), "raw confidence decimal leaked"
    assert any(b in md for b in ("عالية (", "متوسطة (", "منخفضة ("))


def test_render_markdown_other_candidate_markets_section_exists():
    """قسم "الأسواق المرشّحة الأخرى" (جديد) يغطي الأسواق ٢-٨ بجمل تجارية
    سردية — لا تفريغ components_detail خام، ولا ثقة عشرية خامة."""
    import re
    _seed_store_multi()
    from silk_render import build_view
    from silk_reports import render_markdown
    view = build_view(_analyzed_multi())
    assert len(view["markets"]) >= 2
    md = render_markdown(view)
    assert "## الأسواق المرشّحة الأخرى" in md
    assert not re.search(r"ثقة:\s*0\.\d", md)
    assert "الثقة الإجمالية لهذا التقييم:" in md


def test_ai_report_surfaces_in_view_and_replaces_exec_summary():
    """ai_report (التحليل الاحترافي، silk_ai_judge) يصل build_view ويستبدل
    به قسم الخلاصة التنفيذية في كلا الصيغتين حين يتوفر — بدل exec_summary
    الحتمية (silk_narrative)."""
    _seed_store()
    from silk_render import build_view
    from silk_reports import render_markdown
    res = _analyzed()
    res["report"] = ("فقرة احترافية أولى عن أفضل الأسواق.\n"
                     "فقرة ثانية عن الفجوات والخطوة التالية.")
    res["report_note"] = None
    view = build_view(res)
    assert view["ai_report"] == res["report"]
    md = render_markdown(view)
    assert "فقرة احترافية أولى" in md
    # الخلاصة الحتمية (تبدأ كل فقرة أولى بـ"التوصية: ") لا تظهر بديلاً بعد
    # توفر التحليل الاحترافي — لا حكمان في قسم واحد.
    exec_section = md.split("## منهجية البحث")[0]
    assert "التوصية: " not in exec_section


def test_ai_report_absent_falls_back_to_exec_summary_with_declared_note():
    """غياب مفتاح Claude (أو فشل النداء) يرجع للخلاصة الحتمية بلا كسر —
    والملاحظة المعلنة (report_note) تظهر لا تُخفى."""
    _seed_store()
    from silk_render import build_view
    from silk_reports import render_markdown
    res = _analyzed()
    res["report"] = None
    res["report_note"] = ("تعذّر توليد تقرير كلود (مفتاح غائب أو فشل "
                          "النداء) — AI report unavailable, not hidden.")
    view = build_view(res)
    assert view["ai_report"] is None
    md = render_markdown(view)
    assert "التوصية: " in md
    assert "تعذّر توليد تقرير كلود" in md


def test_render_docx_candidate_markets_are_narrative_not_raw_dump():
    """قسم ٩ (docx) يعرض جملاً تجارية بمصدر لكل سوق مرشّح — لا مفتاحاً/قيمة
    خامة يتبعها رقم ثقة عشري."""
    import re
    pytest.importorskip("docx")
    _seed_store_multi()
    from conftest import docx_all_text
    from silk_render import build_view
    from silk_reports import render_docx
    view = build_view(_analyzed_multi())
    path = render_docx(view, os.path.join(tempfile.mkdtemp(), "r.docx"))
    texts = docx_all_text(path)
    assert "٩." in texts
    assert not re.search(r"ثقة:\s*0\.\d", texts)
    assert "الثقة الإجمالية لهذا التقييم" in texts


def test_ui_has_eight_screens_and_markdown_link():
    html = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web", "index.html"),
        encoding="utf-8").read()
    assert "report.md" in html                       # رابط تقرير Markdown
    for marker in ("القرار", "حجم السوق", "المنافسة", "التسعير",
                   "الاشتراطات", "المخاطر"):
        assert marker in html, marker

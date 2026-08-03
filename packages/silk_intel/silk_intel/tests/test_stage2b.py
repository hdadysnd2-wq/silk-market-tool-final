"""اختبارات Stage 2B — إنفاذ خصوصية السوق (بوابة العتبات + الترويسة).

يقفل: (١) ترويسة التقرير: منتج/HS/سوق مستهدف/تاريخ/تغطية %؛ (٢) بوابة العتبة:
دون الحد يُعرض «بيانات غير كافية» + المصادر المُحاوَلة — لا نثر عام؛ (٣) فوق
الحد يُعرض المحتوى المرصود؛ (٤) العتبات المقترحة معلنة قابلة للضبط.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_render import (SECTION_THRESHOLDS, build_view,  # noqa: E402
                         insufficient_line, render_text)


def _starved_view():
    return build_view({"product": "تمور", "hs_code": "080410", "year": 2023,
                       "classified": True,
                       "markets": [{"country": "China", "iso3": "CHN",
                                    "total_score": 0.0, "confidence": 0.0,
                                    "components": {}}]})


def test_header_has_product_hs_market_date_coverage():
    v = _starved_view()
    h = v["header"]
    assert h["product"] == "تمور" and h["hs_code"] == "080410"
    assert h["origin"] == "SAU" and h["target_market"] == "China"
    assert h["date"] and h["coverage_pct"] == 0.0


def test_thresholds_are_declared_and_sane():
    assert SECTION_THRESHOLDS["market_size"] == 2
    assert SECTION_THRESHOLDS["regulatory"] == 2
    assert all(t >= 1 for t in SECTION_THRESHOLDS.values())


def test_starved_sections_render_insufficient_never_generic_prose():
    v = _starved_view()
    st = v["markets"][0]["section_status"]
    assert all(s["status"] == "insufficient" for s in st.values())
    txt = render_text(v)
    assert "بيانات غير كافية لقسم" in txt
    assert "المصادر المُحاوَلة" in txt
    # الحشو القديم ممنوع بنيوياً في النص المُبوَّب.
    assert "يتطلب مفتاح بحث الويب" not in txt


def test_sections_above_threshold_render_facts():
    dp = {"value": 1.0, "source": "World Bank", "confidence": 0.9,
          "note": "x", "retrieved_at": "2026"}
    v = build_view({"product": "تمور", "hs_code": "080410", "year": 2023,
                    "classified": True,
                    "markets": [{"country": "UAE", "iso3": "ARE",
                                 "total_score": 0.5, "confidence": 0.5,
                                 "components": {},
                                 "risk": [dict(dp), dict(dp, note="y")]}]})
    st = v["markets"][0]["section_status"]["risk"]
    assert st["status"] == "ok" and st["contributed"] == 2


def test_docx_gated_section_contains_only_the_insufficiency_sentence():
    import pytest
    pytest.importorskip("docx")
    from docx import Document
    from silk_reports import render_docx
    path = render_docx(_starved_view(),
                       os.path.join(tempfile.mkdtemp(), "g.docx"))
    joined = "\n".join(p.text for p in Document(path).paragraphs)
    # 5b + P2-7: وجه التقرير هادئ (بلا صياح INSUFFICIENT DATA)؛ شفافية 2B
    # (جملة النقص + المصادر المُحاوَلة) انتقلت إلى ملحق المحلّل — مرة واحدة.
    assert "INSUFFICIENT DATA" not in joined
    assert "أقسام دون عتبة الكفاية" in joined
    assert "بيانات غير كافية" in joined
    assert "المصادر المُحاوَلة" in joined
    assert "LOCALPRICE_API_KEY" not in joined      # النثر الإرشادي القديم زال

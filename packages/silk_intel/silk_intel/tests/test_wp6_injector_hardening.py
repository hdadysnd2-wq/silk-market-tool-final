"""WP-6 (برنامج إصلاح جودة التقارير) — تصليب حاقنات ما بعد المعالجة.

كلا العيبين المُسلَّمين (2026-07-22) مُصلَحان في حزمة v2.1 — هذا الملف
**أقفال انحدار** بالجُمل الفعلية من التقارير المُسلَّمة + متغيّرات عدائية
(شرح بقوس/شرطة/نقطتين؛ سنة داخل مسار نمو)، لا إعادة تنفيذ:

- §D-2: «بيانات 2019 (الأحدث المتاح)» خُتمت داخل مسار نمو يمتد فعلياً إلى
  2023–2024 — سنة تُذكَر مع سنة أحدث في نفس الجملة لا تُوسَم.
- §D-1: CAGR/HHI عُرِّفا مرتين متتاليتين بتداخل مكسور — شرح الكاتب بشرطة/
  نقطتين يُحتسَب شرحاً فلا يُحقَن تعريف ثانٍ.
- القاعدة الدائمة: كل الحاقنات تعمل في نموذج العرض (build_view) **قبل**
  بوابة الجودة التي تقرأ النص النهائي نفسه.

Run: python3 -m pytest tests/test_wp6_injector_hardening.py -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── §D-2: وسم السنة المتقادمة لا يدخل مسار نمو ──────────────────────────────

def test_delivered_sentence_growth_span_year_not_tagged_stale():
    """الجملة المُسلَّمة: سلسلة نمو من 2019 إلى 2023 — 2019 لا تُوسَم
    «الأحدث المتاح» وسط مسارها الخاص."""
    from silk_render import _tag_stale_years
    s = "نما الطلب من 8% في 2019 إلى 12% في 2023 وفق UN Comtrade."
    out = _tag_stale_years(s, {2019})
    assert "الأحدث المتاح" not in out


def test_growth_span_adversarial_variants():
    from silk_render import _tag_stale_years
    v1 = "ارتفعت الواردات من 5 مليون دولار عام 2021 إلى 7 مليون دولار عام 2024."
    assert "الأحدث المتاح" not in _tag_stale_years(v1, {2021})
    # سنة متقادمة وحيدة بلا سنة أحدث في جملتها — تُوسَم فعلاً.
    v2 = "بيانات 2019 تُظهر حجم سوق 9 مليون دولار."
    assert "الأحدث المتاح" in _tag_stale_years(v2, {2019})
    # الجملة التالية منفصلة بنقطة: النمو في جملة والسنة القديمة في أخرى.
    v3 = "بلغ الحجم ذروته في 2019. وتُظهر بيانات 2023 استقراراً."
    assert "الأحدث المتاح" in _tag_stale_years(v3, {2019})


# ── §D-1: لا تعريف مزدوج لمصطلح شرحه الكاتب ─────────────────────────────────

def test_delivered_sentence_dash_explained_cagr_not_redefined():
    from silk_render import _apply_merchant_language
    s = "النمو السنوي المركب CAGR — معدل نمو سنوي مركب بلغ 5% خلال الفترة."
    out, _ = _apply_merchant_language(s)
    assert out.count("متوسط النمو السنوي المركّب") == 0


def test_explained_variants_paren_dash_colon_not_redefined():
    from silk_render import _apply_merchant_language
    paren = "مؤشر HHI (مؤشر يقيس تركّز السوق بين المورّدين) بلغ 2900."
    out, _ = _apply_merchant_language(paren)
    assert out.count("مؤشر يقيس تركّز السوق") == 1
    colon = "CAGR: معدل النمو السنوي المركب للفترة 5%."
    out2, _ = _apply_merchant_language(colon)
    assert "متوسط النمو السنوي المركّب" not in out2


def test_unexplained_term_gets_glossed_exactly_once():
    from silk_render import _apply_merchant_language
    s = "بلغ CAGR نحو 5% ثم استقر CAGR بعدها."
    out, glossary = _apply_merchant_language(s)
    assert out.count("متوسط النمو السنوي المركّب") == 1
    assert any(g.get("term") == "CAGR" for g in glossary)


# ── القاعدة الدائمة: الحاقنات قبل البوابة ───────────────────────────────────

def test_injectors_run_in_view_before_gate_reads_same_text():
    """build_view يحقن (مسرد/وسم تقادم/عملة) في نص التقرير القانوني، وبوابة
    الجودة تقرأ النص المحقون نفسه — لا نص خام يصل البوابة أو المُصدِّرات."""
    import silk_quality_gate as G
    from silk_render import build_view
    from tools.canonical_kuwait_peanut_butter import kuwait_research_blob
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(kuwait_research_blob())
    text = view["deep_research"]["report"]["text"]
    assert "مؤشر يقيس تركّز السوق بين المورّدين" in text   # حاقن المسرد عمل
    gate_out = G.run_quality_gate(view)
    assert isinstance(gate_out.get("verdict"), str)  # البوابة قرأت نفس النص

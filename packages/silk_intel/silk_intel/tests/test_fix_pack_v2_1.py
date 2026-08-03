"""حزمة الفكس v2.1 (peanut butter / KWT، 2026-07-22) — أقفال الفحوصات
الجديدة لبوابة الجودة وطبقة العرض.

كل بند من الحزمة يُقابَل بقفلٍ حتمي هنا: الفحص يُفشِل على العيّنة «الذهبية
السيّئة» (golden-bad، تُعيد إنتاج العطل الحي) ويمرّ على النظيف. هرمتي بالكامل
— لا شبكة، لا مفتاح.

Run: python3 -m pytest tests/test_fix_pack_v2_1.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _hits(dr: dict) -> set:
    import silk_quality_gate as qg
    out = qg.run_quality_gate({"deep_research": dr})
    return {f["check"] for f in out["findings"]}


def _dr(report_text: str = "", missions: dict | None = None,
        analyst: dict | None = None, verdict: dict | None = None,
        flip_conditions=None) -> dict:
    dr = {"report": {"text": report_text},
          "missions": missions or {},
          "analyst": analyst or {"by_category": {}, "missing_categories": []},
          "verdict": verdict or {"verdict": "WATCH"}}
    if flip_conditions is not None:
        dr["flip_conditions"] = flip_conditions
    return dr


_FULL_SECTIONS = "\n".join(
    f"## {i}. {s}\nنصّ القسم كامل هنا بجملة تنتهي بنقطة."
    for i, s in enumerate((
        "الخلاصة التنفيذية", "منهجية البحث ونطاقه", "نظرة عامة على السوق وحجمه",
        "ديناميكيات السوق", "تحليل المستهلك والطلب", "المشهد التنافسي",
        "التنظيم والوصول للسوق", "اللوجستيات وسلسلة الإمداد", "تقييم المخاطر",
        "التوصيات الاستراتيجية", "الملاحق"), 1))


# ── §B: بتر/إحالة معلَّقة/شظية يتيمة ─────────────────────────────────────────

def test_orphan_short_token_flagged():
    bad = _FULL_SECTIONS + "\n\nالتحليل النهائي يبيّن تحققا ت"
    assert "orphan_short_token" in _hits(_dr(bad))


def test_clean_text_has_no_orphan_token():
    assert "orphan_short_token" not in _hits(_dr(_FULL_SECTIONS))


def test_dangling_method_note_reference_flagged():
    bad = _FULL_SECTIONS + "\n\nانظر الملاحظة المنهجية في القسم التالي."
    assert "dangling_cross_reference" in _hits(_dr(bad))


def test_resolvable_cross_reference_not_flagged():
    ok = _FULL_SECTIONS.replace(
        "## 2. منهجية البحث ونطاقه\nنصّ القسم كامل هنا بجملة تنتهي بنقطة.",
        "## 2. منهجية البحث ونطاقه\nهذه ملاحظة منهجية عن رمز HS البديل.")
    ok += "\n\nراجع «منهجية البحث ونطاقه» أعلاه للتفصيل."
    assert "dangling_cross_reference" not in _hits(_dr(ok))


def test_client_section_placeholder_flagged_when_no_body_no_facts():
    # سرد يخلو من أقسام العميل المطلوبة ومن حقائق تقاطع => قسم نائب
    bad = "## 1. الخلاصة التنفيذية\nنصّ."
    assert "client_section_placeholder" in _hits(_dr(bad))


# ── §C: الاتساق الرقمي ───────────────────────────────────────────────────────

def test_near_duplicate_figures_flagged():
    bad = _FULL_SECTIONS + ("\n\nبلغت الواردات 6,733,369 دولاراً في التقرير، "
                            "وفي جدولٍ آخر 6,733,376 دولاراً.")
    assert "near_duplicate_figure" in _hits(_dr(bad))


def test_distinct_figures_not_flagged():
    ok = _FULL_SECTIONS + ("\n\nالواردات 6,733,369 دولاراً والصادرات "
                          "2,120,000 دولاراً.")
    assert "near_duplicate_figure" not in _hits(_dr(ok))


def test_hhi_false_precision_flagged():
    bad = _FULL_SECTIONS + "\n\nمؤشر التركّز HHI = 2184.7 في هذا السوق."
    assert "hhi_false_precision" in _hits(_dr(bad))


def test_hhi_integer_not_flagged():
    ok = _FULL_SECTIONS + "\n\nمؤشر التركّز HHI = 2185 في هذا السوق."
    assert "hhi_false_precision" not in _hits(_dr(ok))


def test_supplier_rank_gap_flagged():
    bad = _FULL_SECTIONS + ("\n\nالموردون: #1 تونس، #2 الجزائر، #5 إيران، "
                           "#6 المغرب.")
    assert "supplier_rank_gap" in _hits(_dr(bad))


def test_contiguous_supplier_ranks_not_flagged():
    ok = _FULL_SECTIONS + ("\n\nالموردون: #1 تونس، #2 الجزائر، #3 إيران، "
                          "#4 المغرب.")
    assert "supplier_rank_gap" not in _hits(_dr(ok))


# ── §D: تنسيق النسبة المئوية ────────────────────────────────────────────────

def test_stray_percent_punctuation_flagged():
    bad = _FULL_SECTIONS + "\n\nنما السوق بنسبة .%68 خلال الفترة."
    assert "stray_percent_punctuation" in _hits(_dr(bad))


def test_correct_percent_not_flagged():
    ok = _FULL_SECTIONS + "\n\nنما السوق بنسبة 68% خلال الفترة."
    assert "stray_percent_punctuation" not in _hits(_dr(ok))


def test_render_fixes_stray_percent():
    from silk_render import _apply_merchant_language
    fixed, _ = _apply_merchant_language("نما بنسبة .%68 هذا العام.")
    assert ".%68" not in fixed
    assert "68%" in fixed


# ── §D-1/§D-2: شرح المصطلح مرّة واحدة + وسم التقادم الصحيح ────────────────────

def test_term_defined_once_when_writer_used_dash():
    from silk_render import _apply_merchant_language
    txt = "معدل النمو CAGR — معدل نمو سنوي مركّب مهمّ، وCAGR ثابت لاحقاً."
    out, gloss = _apply_merchant_language(txt)
    # لا حقن تعريفٍ ثانٍ بين قوسين مباشرةً بعد الشرح بالشرطة
    assert out.count("(متوسط النمو السنوي المركّب)") == 0


def test_stale_tag_skips_year_in_growth_span():
    from silk_render import _tag_stale_years
    txt = "نما من 8% في 2019 إلى 12% في 2023 بقوّة."
    out = _tag_stale_years(txt, stale_fact_years={2019})
    # 2019 داخل مسار نمو مع 2023 الأحدث => لا وسم «الأحدث المتاح»
    assert "2019 (الأحدث المتاح)" not in out
    assert "بيانات 2019" not in out


# ── §F: التسمية والنطاقات ────────────────────────────────────────────────────

def test_entity_near_duplicate_flagged():
    bad = _FULL_SECTIONS + ("\n\nالمنافس Taste of Nature قوي، ويظهر أيضاً "
                           "Nature of Taste في السوق.")
    assert "entity_near_duplicate" in _hits(_dr(bad))


def test_confidence_band_mismatch_flagged():
    bad = _FULL_SECTIONS + "\n\nنقيّم هذا بثقة عالية (68%) بناءً على الأدلة."
    assert "confidence_band_mismatch" in _hits(_dr(bad))


def test_confidence_band_correct_not_flagged():
    ok = _FULL_SECTIONS + "\n\nنقيّم هذا بثقة متوسطة (68%) بناءً على الأدلة."
    assert "confidence_band_mismatch" not in _hits(_dr(ok))


def test_confidence_phrase_uses_new_bands():
    from silk_narrative import confidence_phrase
    assert confidence_phrase(0.68).startswith("متوسطة")  # 68% => متوسطة (60-79)
    assert confidence_phrase(0.80).startswith("عالية")   # 80% => عالية
    assert confidence_phrase(0.59).startswith("منخفضة")  # 59% => منخفضة


def test_google_transliteration_unified():
    from silk_render import _apply_merchant_language
    out, _ = _apply_merchant_language("رصدنا عبر غوغل و قوقل معاً.")
    assert "غوغل" not in out
    assert "قوقل" in out


def test_hhi_glossary_wording_is_high_concentration_not_single_player():
    from silk_style_contract import GLOSSARY
    assert "سيطرة لاعب واحد" not in GLOSSARY["HHI"]
    assert "تركّز مرتفع" in GLOSSARY["HHI"]


# ── §G: تصحيحات الحقائق ─────────────────────────────────────────────────────

def test_lpi_invalid_edition_year_flagged():
    bad = _FULL_SECTIONS + "\n\nمؤشر LPI للكويت 3.2 لعام 2022 مرتفع."
    assert "lpi_invalid_edition_year" in _hits(_dr(bad))


def test_lpi_valid_edition_year_not_flagged():
    ok = _FULL_SECTIONS + "\n\nمؤشر LPI للكويت 3.2 لعام 2023 مرتفع."
    assert "lpi_invalid_edition_year" not in _hits(_dr(ok))


# ── §H: تماسك منطق القرار ───────────────────────────────────────────────────

def test_recommendation_tier_mislabel_flagged():
    dr = _dr(
        report_text=_FULL_SECTIONS + "\n\nالتوصية بالدخول قوية جداً.",
        verdict={"verdict": "CONDITIONAL-GO",
                 "ai": {"verdict": "CONDITIONAL-GO"}})
    assert "recommendation_tier_mislabel" in _hits(dr)


def test_conditional_verdict_without_strong_label_not_flagged():
    dr = _dr(
        report_text=_FULL_SECTIONS + "\n\nنوصي بدخول مشروط بتأمين الأهلية.",
        verdict={"verdict": "CONDITIONAL-GO",
                 "ai": {"verdict": "CONDITIONAL-GO"}})
    assert "recommendation_tier_mislabel" not in _hits(dr)

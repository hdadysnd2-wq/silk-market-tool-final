"""أقفالُ الهوتفكس (بلاغ قطر × HS 200811، ٢٠٢٦-٠٧-٢٣) — هرمتيةٌ بالكامل:

- HF1: معرّفُ المصدر ذرّيّ؛ المراجع/المنهجية تُسطّح `source_ids` فيُسنِد كلُّ
  مصدرٍ لرابطه الصحيح، بلا معرّفٍ مركّبٍ ولا تكرار.
- HF2: لا خليةَ جدولٍ تُبتَر داخل رقمٍ ولا قوسُ استشهادٍ فارغ «()»/«(/)».
- HF3: مقدارُ «حجم سوق» متعارضٌ مع مرتكزات التشغيلة يُوسَم ويُتحفَّظ عليه.
- HF4: لا سلسلةٌ إنجليزيةٌ داخلية في المتن؛ سطرُ إفصاح التنقية للمدقّق فقط؛
  اتساقُ حالة الكيان؛ فجوةُ الوزن مصرَّحةٌ بدقّة.

Run:  python3 -m pytest tests/test_hf_attribution_truncation_plausibility.py -q
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SILK_HERMETIC", "1")


# ── HF1: إسنادٌ ذرّيّ ─────────────────────────────────────────────────────────

def test_atomic_source_id_rejects_join_separators_allows_slash():
    from silk_data_layer import is_atomic_source_id
    assert is_atomic_source_id("World Bank")
    assert is_atomic_source_id("WITS/WTO Tariff")      # «/» ليست دمجاً
    assert not is_atomic_source_id("IMF WEO، World Bank")
    assert not is_atomic_source_id("GCC secretariat؛ GAFTA secretariat")


def test_atomic_source_ids_prefers_explicit_list_then_splits_legacy():
    from silk_data_layer import atomic_source_ids
    assert atomic_source_ids("IMF WEO", ("IMF WEO", "World Bank")) == [
        "IMF WEO", "World Bank"]
    # سلسلةٌ قديمةٌ مركّبة تُقسَّم دفاعياً.
    assert atomic_source_ids("GCC secretariat، GAFTA secretariat") == [
        "GCC secretariat", "GAFTA secretariat"]
    # فريدةٌ محفوظةُ الترتيب.
    assert atomic_source_ids(None, ("A", "a", "B")) == ["A", "B"]


def test_agreement_secretariats_resolve_to_own_urls():
    from silk_data_layer import public_source_url
    assert public_source_url("GCC secretariat") == "https://gcc-sg.org"
    assert public_source_url("GAFTA secretariat") == "https://www.lasportal.org"
    assert public_source_url("OIC secretariat") == "https://www.oic-oci.org"
    # لا يتصادمان: كلٌّ رابطُه.
    assert public_source_url("IMF WEO") != public_source_url("World Bank")


def _references_text(result):
    """نصُّ قسم «المراجع» من تقرير العميل المُصيَّر — هرمتيّ."""
    import silk_render
    import silk_reports
    from docx import Document
    view = silk_render.build_view(result)
    path = os.path.join(tempfile.mkdtemp(), "c.docx")
    silk_reports.render_client_docx(view, path)
    doc = Document(path)
    lines = [p.text for p in doc.paragraphs]
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "المراجع")
    return "\n".join(lines[start + 1:])


def test_three_source_finding_yields_three_atomic_references():
    """عقدُ الأمر الحرفيّ: بندٌ أسنَده ٣ مصادرَ ⇒ ٣ مراجعَ ذرّيةٍ بروابطَ ٣
    متمايزةٍ صحيحة، وصفرُ سلسلةٍ مركّبةٍ في أيّ مكان."""
    from silk_data_layer import DataPoint
    from silk_agents import AgentReport
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Qatar")
    dp = DataPoint("مؤشّرٌ اقتصاديّ مؤكَّد", "IMF WEO", 0.9, "note", "2026-07-23",
                   source_ids=("IMF WEO", "World Bank", "OpenAlex"))
    result = {
        "product": "زبدة الفول السوداني", "hs_code": "200811", "year": 2023,
        "market": {"iso3": ref.iso3, "m49": ref.m49, "iso2": ref.iso2,
                  "name_en": ref.name_en, "name_ar": ref.name_ar},
        "markets": [],
        "deep_research": {"missions": {
            "demographics_economy": AgentReport("LLMAgent:demographics_economy",
                                                [dp], False, "s")},
            "analyst": {"report": AgentReport("LLMAgent:market_analyst", [dp],
                                              False, "s"),
                       "by_category": {}, "missing_categories": []},
            "verdict": {"verdict": "WATCH", "ai": {"verdict": "WATCH",
                                                   "reasoning": "r"}},
            "report": {"report": "## 1. الخلاصة التنفيذية\nنصّ.\n",
                      "review_cycles": 1, "unresolved_notes": []}}}
    refs = _references_text(result)
    for src, url in (("IMF WEO", "imf.org"), ("World Bank", "albankaldawli"),
                     ("OpenAlex", "openalex.org")):
        assert src in refs, f"{src} مفقودٌ من المراجع"
        assert url in refs, f"رابط {src} ({url}) مفقود"
    # صفرُ سلسلةٍ مركّبة (فاصلُ دمجٍ عربيّ بين اسمين).
    assert "IMF WEO، World Bank" not in refs
    assert "، World Bank —" not in refs


def test_qatar_fixture_references_gafta_and_gcc_distinctly():
    import tools.canonical_qatar_peanut_butter as Q
    refs = _references_text(Q.qatar_research_blob())
    assert "GCC secretariat" in refs and "gcc-sg.org" in refs
    assert "GAFTA secretariat" in refs and "lasportal.org" in refs
    assert "GCC secretariat، GAFTA" not in refs   # لا معرّفٌ مركّب


def test_methodology_has_no_duplicate_source_names():
    import tools.canonical_qatar_peanut_butter as Q
    import silk_reports
    para = silk_reports._client_methodology_paragraph(
        Q.qatar_research_blob()["deep_research"])
    # لا اسمٌ مكرّرٌ في سطر «اعتمد هذا التقرير…».
    for name in ("GCC secretariat", "GAFTA secretariat", "IMF WEO",
                 "World Bank"):
        assert para.count(name) <= 1, f"{name} مكرّرٌ في المنهجية"


# ── HF2: بترٌ/أقواسٌ فارغة ────────────────────────────────────────────────────

def test_trim_sentence_never_ends_inside_a_number():
    from silk_reports import _trim_sentence
    src = ("تعافٍ جزئيّ إلى 7.12 مليون دولار بسعرِ صرفٍ ثابتٍ عند 3.65 ريال "
           "وقيمةِ السعودية 3.5 بالمئة من الإجمالي المرصود")
    for n in (30, 34, 38, 40, 42, 50, 60):
        out = _trim_sentence(src, n)
        assert not out.rstrip().endswith("."), (n, out)
        assert not out.rstrip().endswith("،"), (n, out)
        # لا «رقم+نقطة» في النهاية (بترٌ داخل رقم).
        import re
        assert not re.search(r"[0-9٠-٩][.،]\s*$", out), (n, out)


def test_strip_internal_plumbing_removes_citation_group_no_empty_parens():
    from silk_render import _strip_internal_plumbing
    assert "()" not in _strip_internal_plumbing("المتاجر (dp3) هي كارفور")
    assert "()" not in _strip_internal_plumbing("مصدر (dp3، dp4) مؤكَّد")
    out = _strip_internal_plumbing("القيمة (dp7)")
    assert "(" not in out and ")" not in out
    # سلسلةُ الشرطة المائلة (خلايا markdown: | → /) لا تترك «(///)».
    assert "(/)" not in _strip_internal_plumbing("خلية (dp1/dp2/dp3) قيمة")


def test_client_sanitize_collapses_empty_paren_residue():
    from silk_reports import _client_sanitize
    for junk in ("()", "( )", "(/)", "(///)", "(،)"):
        assert _client_sanitize(f"قيمة {junk} مؤكَّدة") == "قيمة مؤكَّدة"


def test_qatar_and_nld_samples_have_no_truncation_artifacts():
    import silk_evals as E
    import tools.canonical_qatar_peanut_butter as Q
    import tools.gen_client_report_sample as gcs
    case = {"structural": {"no_truncation_artifacts": True}}
    for blob in (gcs.result, Q.qatar_research_blob()):
        out = E.structural_checks(blob, case)
        assert out["passed"], out["failures"]


# ── HF3: معقوليةٌ عبر المصادر ────────────────────────────────────────────────

def test_plausibility_flags_implausible_market_size():
    import silk_plausibility as P
    import tools.canonical_qatar_peanut_butter as Q
    flags = P.check_magnitudes(Q.qatar_research_blob())
    assert flags, "497م$ مقابل واردات 7م$ يجب أن يُوسَم"
    assert flags[0]["kind"] == "market_size_magnitude"
    assert flags[0]["detail"]["import_ratio"] > 20


def test_num_usd_scale_word_is_bounded_not_substring():
    """مراجعةٌ ذاتية (HIGH): «الف» جزءُ «الفول»/«الفواكه» لا يُضاعِف ×1000.
    المقياسُ يُقرأ ككلمةٍ تاليةٍ للرقم مباشرةً، محدودةً بحدّ."""
    from silk_plausibility import _num_usd
    # رقمٌ مكتوبٌ بالأرقام قربَ كلمةٍ تحوي «الف» ⇒ لا مضاعفة.
    assert _num_usd("حجم سوق الفول السوداني بلغ 497,000,000 دولار") == 497_000_000.0
    assert _num_usd("واردات الفواكه 7,000,000 دولار") == 7_000_000.0
    assert _num_usd("3 الفئات المدروسة") == 3.0            # «الف» في «الفئات»
    # كلمةُ المقياس الحقيقية (تالية للرقم، محدودة) ⇒ تُضاعِف.
    assert _num_usd("497 مليون دولار") == 497_000_000.0
    assert _num_usd("2.5 مليار دولار") == 2_500_000_000.0
    assert _num_usd("500 ألف دولار") == 500_000.0
    assert _num_usd("$3 million wholesale") == 3_000_000.0


def test_plausibility_anchor_not_inflated_by_alif_substring():
    """المرتكزُ (واردات) لا يُنفَخ ×1000 بـ«الف» في «الفول» فيُخفي علامةً حقيقية."""
    import silk_plausibility as P
    result = {"deep_research": {"missions": {
        "trade_flow": {"findings": [{"value": "واردات الفول 7,000,000 دولار",
            "source": "UN Comtrade", "note": "إجمالي استيراد قطر من العالم"}]},
        "consumer_culture": {"findings": [{"value": "497 مليون دولار",
            "source": "ويب", "note": "حجم سوق الفول الكامل"}]}}}}
    flags = P.check_magnitudes(result)
    assert flags, "المرتكزُ الصحيح (7م$) يجب أن يُبقي العلامة قائمة (497م$ = 71×)"
    assert flags[0]["detail"]["import_ratio"] > 20


def test_plausibility_silent_without_anchor_fail_open():
    import silk_plausibility as P
    # لا مرتكزَ وارداتٍ ⇒ لا حكم (فشلٌ آمنٌ مفتوح).
    result = {"deep_research": {"missions": {"consumer_culture": {"findings": [
        {"value": "497 مليون دولار", "source": "ويب",
         "note": "حجم السوق الكامل"}]}}}}
    assert P.check_magnitudes(result) == []


def test_plausibility_disabled_by_env(monkeypatch):
    import silk_plausibility as P
    import tools.canonical_qatar_peanut_butter as Q
    monkeypatch.setenv("SILK_PLAUSIBILITY", "0")
    assert P.check_magnitudes(Q.qatar_research_blob()) == []


def test_build_view_attaches_flags_and_caveat():
    import silk_render
    import tools.canonical_qatar_peanut_butter as Q
    view = silk_render.build_view(Q.qatar_research_blob())
    dr = view.get("deep_research") or {}
    assert dr.get("plausibility_flags"), "العلامة يجب أن تُسجَّل في المانيفست"
    assert any("يتعذّر التوفيق" in ln for ln in (view.get("limits") or [])), \
        "تحفّظُ النطاق يجب أن يظهر للعميل"


def test_qatar_fixture_passes_full_extended_gate():
    """التقريرُ بشكلِ قطرَ الحقيقيّ (بكلّ محفّزات العيوب) يمرّ البوّابةَ الموسَّعة
    بعد الإصلاح — دليلٌ هرمتيٌّ على معايير القبول ١-٣ مجتمعة."""
    import silk_evals as E
    import tools.canonical_qatar_peanut_butter as Q
    case = {"structural": {
        "clean_body": True, "references_integrity": True,
        "no_truncation_artifacts": True, "plausibility_reconciled": True}}
    out = E.structural_checks(Q.qatar_research_blob(), case)
    assert out["passed"], out["failures"]


# ── HF4: تسريباتٌ صغرى ───────────────────────────────────────────────────────

def test_english_preliminary_note_stripped_keeps_arabic():
    from silk_render import _strip_internal_plumbing
    note = ("Preliminary only; missing sources flagged, not estimated. "
            "تنبيه: قرار مبدئي والنواقص معلّمة لا مُخمّنة.")
    out = _strip_internal_plumbing(note)
    assert "Preliminary" not in out and "estimated" not in out
    assert "تنبيه" in out


def test_unverified_entity_annotated_in_prose():
    import silk_reports
    dr = {"importer_leads": {"leads": [
        {"name": "Five Group Trading Company",
         "doc_level": "○ مرشّح ويب غير موثَّق"}]}}
    text = "من الموزّعين Five Group Trading Company في الدوحة."
    out = silk_reports._annotate_unverified_entities(text, dr)
    assert "مرشّح غير موثَّق" in out
    # الموثَّقُ لا يُوسَم.
    dr2 = {"importer_leads": {"leads": [
        {"name": "Ejmar Import BV", "doc_level": "◐ مرصود عبر خرائط قوقل"}]}}
    out2 = silk_reports._annotate_unverified_entities(
        "الموزّع Ejmar Import BV موثَّق.", dr2)
    assert "مرشّح غير موثَّق" not in out2


def test_unverified_entity_no_midword_false_match():
    """مراجعةٌ ذاتية (MEDIUM): اسمٌ غيرُ موثَّقٍ لا يُوسَم داخل كلمةٍ أطول تحويه —
    «Nada» لا يُطابَق داخل «Nadason»، فلا يُفسَد نثرٌ سليم."""
    import silk_reports
    dr = {"importer_leads": {"leads": [
        {"name": "Nada", "doc_level": "○ مرشّح ويب غير موثَّق"}]}}
    out = silk_reports._annotate_unverified_entities(
        "شركة Nadason Trading هي موزّع كبير.", dr)
    assert "Nadason Trading" in out and "مرشّح غير موثَّق" not in out
    # لكنّ الورودَ المستقلَّ يُوسَم.
    out2 = silk_reports._annotate_unverified_entities(
        "من الموزّعين Nada في الدوحة.", dr)
    assert "مرشّح غير موثَّق" in out2


def test_comtrade_reporter_no_weight_declares_gap_precisely():
    from unittest.mock import patch
    from silk_llm_runtime import _tool_comtrade_imports
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Qatar")
    recs = [{"partnerCode": "0", "primaryValue": 7_120_000.0}]  # لا netWgt
    with patch("silk_llm_runtime.comtrade_trade", return_value=recs):
        dps = _tool_comtrade_imports({"years": [2023]}, {
            "market": ref, "hs_code": "200811", "product": "زبدة",
            "extra_findings": [], "extra_context": ""})
    gap = [d for d in dps if d.value is None]
    assert gap and "لا يودع بيانات الوزن" in gap[0].note

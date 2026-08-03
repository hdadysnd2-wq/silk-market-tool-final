"""أقفال إصلاحات مراجعة شيفرة PR #147 — عشرة بنود من المراجعة عالية الجهد.

كل بند هنا نتيجة مراجعة مؤكَّدة/مرجَّحة على فرع برنامج إصلاح جودة التقارير
نفسه، أُصلحت في نفس الجلسة وقُفلت باختبار:

1. نداء الصياغة على مسار التصدير محكوم ببوابة إضافات كلود ومُخزَّن على السجل.
2. ممرّ العرض لا يحوّر قواميس الحقائق المخزنة (نسخ لا مراجع).
3. حارس الشارة/المتن يقرأ الحكم من المصدر الحتمي الواحد.
4. فحص تصنيف التوصية في البوابة يقرأ من المصدر الحتمي الواحد.
5. إبرة النص النائب مميِّزة وغير حساسة للتشكيل («التتبّع» تُلتقط،
   والنثر المشروع «أثر التتبع الرقمي» لا يُحجَب).
6. فحص ما بعد النشر يعامل 409 البوابة حجباً مقصوداً ويثبت الآلية داخلياً.
7. المصالحة الرقمية تشترط هوية سنة متطابقة — لا عنقدة بالتقارب وحده.
8. مُشغِّل تناقض الفجوات كلمة مستقلة — «الفجوات:» السردية لا تُفشِل.
9. قيمة SILK_PDF_BRACKET_FAIL_MAX المشوَّهة لا تُفجِّر تصدير الـPDF.
10. قسم القرار لا يخرج بلا فقرة أساس حتى مع مدوّنة بلا «note».

Run: python3 -m pytest tests/test_pr147_review_fixes.py -q
"""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel: str) -> str:
    return open(os.path.join(_ROOT, rel), encoding="utf-8").read()


# ── ١) نداء الصياغة: محكوم + مُخزَّن ────────────────────────────────────────

def test_export_rephrase_is_gated_and_cached_in_source():
    src = _src("api.py")
    block = src.split("def _block_client_export_if_gate_failed(")[1].split(
        "\n    def ")[0]
    assert "_free_ai_extras_allowed()" in block      # بوابة السقف/الحجب
    assert "save_analysis(" in block                  # تخزين النثر على السجل
    assert "_client_missing_narrative_heads" in block  # لا حجز بلا حاجة فعلية


def test_view_reloads_cached_prose_from_stored_record():
    from silk_render import build_view
    from tools.canonical_kuwait_peanut_butter import kuwait_research_blob
    blob = kuwait_research_blob()
    blob["deep_research"]["client_fallback_prose"] = {
        "المخاطر": "نثر مُخزَّن من تصدير سابق."}
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(blob)
    assert view["deep_research"]["client_fallback_prose"] == {
        "المخاطر": "نثر مُخزَّن من تصدير سابق."}


# ── ٢) لا تحوير لقواميس الحقائق المخزنة ─────────────────────────────────────

def test_build_view_never_mutates_stored_finding_dicts():
    from silk_render import build_view
    from tools.canonical_kuwait_peanut_butter import kuwait_research_blob
    blob = kuwait_research_blob()   # hs غير مؤكَّد => وسم سياقي في العرض
    raw_findings = [f for m in blob["deep_research"]["missions"].values()
                    for f in m["findings"]]
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(blob)
    for f in raw_findings:
        assert "evidence_tag" not in f
        assert "corroborated" not in f
    # الوسم موجود في نسخ العرض (لم يُفقَد الأثر الوظيفي).
    view_findings = [f for m in view["deep_research"]["missions"].values()
                     for f in (m.get("findings") or [])]
    assert any(f.get("evidence_tag") for f in view_findings)


# ── ٣-٤) قارئا الحكم المهاجَران ─────────────────────────────────────────────

def test_watchdog_badge_body_uses_deterministic_verdict():
    from silk_watchdog import _check_badge_body
    dr = {"verdict_label": "مراقبة السوق",
          "verdict": {"verdict": "WATCH", "confidence": 0.5,
                      "ai": {"verdict": "GO", "confidence": 0.9}}}
    status, findings = _check_badge_body(dr)
    assert status["status"] == "match", status
    assert findings == []


def test_gate_tier_check_uses_deterministic_verdict():
    import silk_quality_gate as G
    # حتمي GO + قراءة كلود مشروطة: لا إيجاب كاذب.
    dr = {"report": {"text": "الخلاصة: التوصية بالدخول."},
          "verdict": {"verdict": "GO", "confidence": 0.7,
                      "ai": {"verdict": "CONDITIONAL-GO"}}}
    assert G._check_recommendation_tier_label_consistency(dr) == []
    # حتمي مشروط + متن يرقّي التسمية: يُلتقط.
    dr2 = {"report": {"text": "الخلاصة: التوصية بالدخول."},
           "verdict": {"verdict": "CONDITIONAL-GO", "confidence": 0.7,
                       "ai": {"verdict": "GO"}}}
    assert G._check_recommendation_tier_label_consistency(dr2)


# ── ٥) إبرة النص النائب: مميِّزة وغير حساسة للتشكيل ─────────────────────────

def test_placeholder_needle_matches_vocalized_and_spares_legit_prose():
    import silk_quality_gate as G
    # الهدف الفعلي (بالشدّة كما يصدر من _trim_sentence) يُلتقط.
    vocalized = "بند غامض — التفاصيل في أثر التتبّع."
    assert G._check_placeholder_leak(vocalized)
    assert G.run_client_artifact_text_gate(vocalized)
    # النثر المشروع بالكلمتين العاريتين لا يُحجَب.
    legit = "أثر التتبع الرقمي على سلوك المستورد ملحوظ في هذه الفئة."
    assert G._check_placeholder_leak(legit) == []
    assert G.run_client_artifact_text_gate(legit) == []


# ── ٦) فحص ما بعد النشر: 409 البوابة حجب مقصود ─────────────────────────────

def test_smoke_treats_gate_409_as_intended_and_probes_internal():
    src = _src("tools/post_deploy_smoke.py")
    assert src.count('quality_gate_fail" in (body or b"")') == 2
    assert "report.docx?internal=1" in src
    assert "report.pdf?internal=1" in src


# ── ٧) المصالحة تشترط هوية سنة ─────────────────────────────────────────────

def test_reconciliation_requires_matching_year_identity():
    from silk_render import _reconcile_numeric_conflicts
    # قيمتان متقاربتان لسنتين مختلفتين: ليستا تعارضاً.
    missions = {"a": {"findings": [
        {"value": 6733369.0, "source": "UN Comtrade", "confidence": 0.9,
         "note": "واردات 2023"}]},
        "b": {"findings": [
            {"value": 6733376.0, "source": "World Bank", "confidence": 0.8,
             "note": "مؤشر 2022"}]}}
    assert _reconcile_numeric_conflicts(missions, False) == []
    # قيمة بلا سنة قابلة للاشتقاق لا تدخل المصالحة أصلاً.
    missions2 = {"a": {"findings": [
        {"value": 6733369.0, "source": "UN Comtrade", "confidence": 0.9,
         "note": "واردات 2023"}]},
        "b": {"findings": [
            {"value": 6733376.0, "source": "web", "confidence": 0.6,
             "note": "تقدير عام بلا سنة"}]}}
    assert _reconcile_numeric_conflicts(missions2, False) == []
    # نفس السنة: التعارض الحقيقي يُحسم كما في بلاغ التدقيق.
    missions3 = {"a": {"findings": [
        {"value": 6733369.0, "source": "UN Comtrade", "confidence": 0.9,
         "note": "واردات 2023"}]},
        "b": {"findings": [
            {"value": 6733376.0, "source": "web", "confidence": 0.6,
             "note": "واردات 2023 من بحث ويب"}]}}
    conflicts = _reconcile_numeric_conflicts(missions3, False)
    assert len(conflicts) == 1
    assert conflicts[0]["canonical_value"] == 6733369.0


# ── ٨) مُشغِّل تناقض الفجوات كلمة مستقلة ────────────────────────────────────

def test_gaps_trigger_is_word_bounded():
    import silk_quality_gate as G
    clean_dr = {
        "report": {"text": "الفجوات: لا توجد فجوات جوهرية في هذه الدراسة."},
        "analyst": {"by_category": {"demand": [{"value": "x",
                                                "confidence": 0.9}]},
                   "missing_categories": []},
        "missions": {}, "flip_conditions": []}
    # «الفجوات:» السردية داخل جملة نفيٍ سليمة لا تُفشِل تقريراً صحيحاً.
    assert G._check_gaps_closing_contradiction(clean_dr) == []
    # «فجوة بيانات» الصريحة تبقى مُشغِّلاً.
    dr2 = dict(clean_dr)
    dr2["report"] = {"text": "توجد فجوة بيانات في مؤشرات الحوكمة."}
    assert G._check_gaps_closing_contradiction(dr2)


# ── ٩) قيمة بيئة مشوَّهة لا تقتل تصدير الـPDF ───────────────────────────────

def test_malformed_bracket_limit_env_does_not_crash(monkeypatch):
    import silk_reports as R

    class _FakePage:
        def get_text(self):
            return "( \n( \n( \n( \n"     # ٤ > الافتراضي 3

    class _FakePdf:
        def __enter__(self):
            return [_FakePage()]

        def __exit__(self, *a):
            return False

    monkeypatch.setitem(sys.modules, "fitz",
                        types.SimpleNamespace(open=lambda p: _FakePdf()))
    monkeypatch.setenv("SILK_PDF_BRACKET_FAIL_MAX", "abc")
    # لا ValueError خام — الافتراضي 3 يسري فيُرفَض المستند المعكوس بوضوح.
    with pytest.raises(RuntimeError, match="اتجاه الأقواس"):
        R._pdf_bracket_check("/tmp/any.pdf")


# ── ١٠) لا قسم قرار بلا فقرة أساس ──────────────────────────────────────────

def test_decision_section_always_has_a_basis_paragraph(tmp_path):
    pytest.importorskip("docx")
    from docx import Document
    from silk_render import build_view
    import silk_reports as R
    from tools.canonical_kuwait_peanut_butter import kuwait_research_blob
    blob = kuwait_research_blob()
    # مدوّنة بلا note + قراءة كلود مخالفة (الحالة التي كانت تُفرِغ الأساس).
    blob["deep_research"]["verdict"] = {
        "verdict": "WATCH", "confidence": 0.5,
        "ai": {"verdict": "GO", "confidence": 0.9,
               "reasoning": "ادخل السوق فوراً."}}
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(blob)
    view["test_run"] = True
    out = str(tmp_path / "client.docx")
    R.render_client_docx(view, out)
    paras = [p.text for p in Document(out).paragraphs]
    i = paras.index("التوصية: مراقبة السوق")
    following = [p for p in paras[i + 1:i + 3] if p.strip()]
    assert following and "درجة ثقة" in following[0]
    assert "ادخل السوق فوراً" not in "\n".join(paras)

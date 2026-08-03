"""WP-3 (برنامج إصلاح جودة التقارير) — نزاهة الأدلة: شارات ومصالحة وتفريد.

بلاغ التدقيق (2026-07-22): رقم نموّ رفضه السرد بقي «✓ موثق» في سجل الأدلة؛
قيمتان لواردات 2023 (6,733,369 و6,733,376) تعايشتا في تقرير واحد؛ «GAFTA
secretariat» تكرّرت في سطر المصادر؛ وGoogle Trends أُدرج مصدراً مُستشاراً
في تشغيلة فشلت خدمته فيها. الأقفال:

1. شارة واعية بالمنشأ: بند جمعه وكيل بحث (وسم tool-use داخلي) يُسقَف درجةً
   تحت شارة مصدره المسمّى ما لم يسانده رصد رسمي مباشر.
2. ممرّ مصالحة رقمية: قيمة قانونية واحدة، والمرفوض يُوسَم «متعارض — مستبعد»
   (لا يعرض ✓ أبداً) والتعارض يُفصَح مرة واحدة.
3. تفريد مصادر مُطبَّع + استبعاد مصدرٍ كل بنوده أخطاء من سطر المصادر
   (يُذكَر في الحدود فقط).
4. مسرد HHI: «تركّز مرتفع» لا «سيطرة لاعب واحد» (مُصلَح في v2.1 — قفل فقط).

Run: python3 -m pytest tests/test_wp3_evidence_integrity.py -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ── ١) الشارة الواعية بالمنشأ ───────────────────────────────────────────────

def test_agent_gathered_claim_is_capped_one_tier_below():
    from silk_narrative import evidence_badge_for
    f = {"value": 100.0, "confidence": 0.9,
         "source": "UN Comtrade (Claude tool-use)"}
    assert evidence_badge_for(f) == "◐ ثانوي"          # ✓ → ◐
    f2 = {"value": 100.0, "confidence": 0.6,
          "source": "web (tool-use)"}
    assert evidence_badge_for(f2) == "○ غير متحقق"     # ◐ → ○


def test_corroborated_agent_claim_keeps_named_source_tier():
    from silk_narrative import evidence_badge_for
    f = {"value": 100.0, "confidence": 0.9, "corroborated": True,
         "source": "UN Comtrade (Claude tool-use)"}
    assert evidence_badge_for(f) == "✓ موثّق"


def test_direct_collector_claim_untouched():
    from silk_narrative import evidence_badge_for
    assert evidence_badge_for(
        {"value": 1, "confidence": 0.9, "source": "UN Comtrade"}) == "✓ موثّق"


def test_display_still_strips_tooluse_but_flag_stays_on_datapoint():
    """الوسم يبقى داخلياً على البند ويُجرَّد للعرض فقط."""
    from silk_reports import _clean_source_label
    from silk_narrative import is_agent_gathered
    raw = "UN Comtrade (Claude tool-use)"
    assert _clean_source_label(raw) == "UN Comtrade"
    assert is_agent_gathered(raw) is True


# ── ٢) ممرّ المصالحة الرقمية ────────────────────────────────────────────────

def _missions_with_near_duplicates() -> dict:
    return {
        "trade_flow": {"label": "تدفقات التجارة", "failed": False,
                       "summary": "ok", "findings": [
            {"value": 6733369.0, "source": "UN Comtrade", "confidence": 0.9,
             "note": "واردات 2023", "retrieved_at": "2026-07-20"}]},
        "demand_trends": {"label": "الطلب", "failed": False,
                          "summary": "ok", "findings": [
            {"value": 6733376.0, "source": "UN Comtrade (Claude tool-use)",
             "confidence": 0.6, "note": "واردات 2023 من بحث ويب",
             "retrieved_at": "2026-07-20"}]},
    }


def test_near_duplicate_values_reconcile_to_one_canonical_with_disclosure():
    from silk_render import _reconcile_numeric_conflicts
    from silk_narrative import RECONCILED_OUT_TAG, evidence_badge_for
    missions = _missions_with_near_duplicates()
    conflicts = _reconcile_numeric_conflicts(missions, hs_flagged=False)
    assert len(conflicts) == 1
    assert conflicts[0]["canonical_value"] == 6733369.0
    assert conflicts[0]["rejected_values"] == [6733376.0]
    loser = missions["demand_trends"]["findings"][0]
    assert str(loser["evidence_tag"]).startswith(RECONCILED_OUT_TAG)
    # (أ) القبول: الرقم المرفوض لا يعرض «✓» أبداً.
    assert evidence_badge_for(loser) == RECONCILED_OUT_TAG
    winner = missions["trade_flow"]["findings"][0]
    assert "evidence_tag" not in winner


def test_identical_values_are_not_a_conflict():
    from silk_render import _reconcile_numeric_conflicts
    missions = {"a": {"findings": [
        {"value": 5000000.0, "source": "UN Comtrade", "confidence": 0.9}]},
        "b": {"findings": [
            {"value": 5000000.0, "source": "World Bank", "confidence": 0.8}]}}
    assert _reconcile_numeric_conflicts(missions, False) == []


def test_hs_flagged_comtrade_figures_never_render_verified():
    """رقم أعاد السردُ تأطيره «مؤشراً سياقياً» (رمز HS غير مؤكَّد) لا يبقى
    «✓ موثق» في سجل الأدلة — حالة رقم النموّ المرفوض المُسلَّمة."""
    from silk_render import _reconcile_numeric_conflicts
    from silk_narrative import evidence_badge_for
    missions = {"trade_flow": {"findings": [
        {"value": 9000000.0, "source": "UN Comtrade", "confidence": 0.9}]}}
    _reconcile_numeric_conflicts(missions, hs_flagged=True)
    f = missions["trade_flow"]["findings"][0]
    assert str(f.get("evidence_tag") or "").startswith("مؤشر سياقي")
    assert evidence_badge_for(f) == "◐ ثانوي"


def test_reconciled_out_finding_excluded_from_client_references(tmp_path):
    pytest.importorskip("docx")
    from docx import Document
    from silk_reports import _client_references_section
    from silk_narrative import RECONCILED_OUT_TAG
    dr = {"missions": {"m": {"findings": [
        {"value": 6733376.0, "source": "UN Comtrade", "confidence": 0.9,
         "note": "", "retrieved_at": "2026-07-20",
         "evidence_tag": f"{RECONCILED_OUT_TAG} — القيمة القانونية 6733369"},
    ]}}}
    doc = Document()
    _client_references_section(doc, dr)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "comtradeplus" not in text.lower()   # لا مرجع لبند مستبعد


def test_view_attaches_reconciliation_conflicts():
    from silk_render import build_view
    from tools.canonical_kuwait_peanut_butter import kuwait_research_blob
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(kuwait_research_blob())
    rec = view["deep_research"].get("reconciliation")
    assert isinstance(rec, dict) and "conflicts" in rec


# ── ٣) تفريد المصادر واستبعاد الفاشل كلياً ──────────────────────────────────

def test_methodology_sources_deduped_after_normalization():
    from silk_reports import _client_methodology_paragraph
    dr = {"missions": {
        "a": {"findings": [{"value": 1, "source": "GAFTA secretariat",
                            "retrieved_at": "2026-07-20"}]},
        "b": {"findings": [{"value": 2, "source": "GAFTA  Secretariat "}]},
    }}
    text = _client_methodology_paragraph(dr)
    assert text.lower().count("gafta") == 1


def test_all_error_source_excluded_from_sources_line():
    """مصدرٌ كل بنوده أخطاء (فشلت خدمته في التشغيلة) لا يظهر في سطر
    «اعتمد هذا التقرير على مصادر…» — حالة Google Trends المُسلَّمة."""
    from silk_reports import _client_methodology_paragraph
    dr = {"missions": {
        "a": {"findings": [{"value": 1, "source": "UN Comtrade",
                            "retrieved_at": "2026-07-20"}]},
        "t": {"findings": [
            {"value": None, "source": "Google Trends",
             "note": "فشل الجلب — الخدمة غير متاحة"},
            {"value": None, "source": "Google Trends", "note": "مهلة"}]},
    }}
    text = _client_methodology_paragraph(dr)
    assert "Google Trends" not in text
    assert "UN Comtrade" in text


def test_failing_source_mentioned_in_limits_only():
    from silk_render import build_view
    from tools.canonical_kuwait_peanut_butter import kuwait_research_blob
    blob = kuwait_research_blob()
    blob["deep_research"]["missions"]["demand_trends"] = {
        "agent_name": "LLMAgent:demand_trends", "failed": False,
        "summary": "جُمِعت مؤشرات جزئية",
        "findings": [{"value": None, "source": "Google Trends",
                      "confidence": 0.0, "note": "فشل الجلب",
                      "retrieved_at": "2026-07-20"}]}
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(blob)
    limits = view["deep_research"].get("limits") or []
    assert any("Google Trends" in l for l in limits)


# ── ٤) مسرد HHI (مُصلَح في v2.1 — قفل انحدار فقط) ───────────────────────────

def test_hhi_glossary_says_high_concentration_not_single_player():
    from silk_style_contract import GLOSSARY
    assert "تركّز مرتفع" in GLOSSARY["HHI"]
    assert "سيطرة لاعب واحد" not in GLOSSARY["HHI"]

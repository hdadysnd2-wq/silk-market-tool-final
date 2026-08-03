"""WP-7 (برنامج إصلاح جودة التقارير) — تصليب بوابة التسليم.

الحالة قبل الفكس: `?override=1` كان يتخطّى حجب بوابة الجودة بنفس مفتاح
API العادي؛ ولا فحص على نصّ المُنتَج النهائي المبني (docx → PDF) — فقط على
القالب. الأقفال:

1. التجاوز يتطلّب سلطة مالك منفصلة (`SILK_OWNER_KEY` عبر `X-Owner-Key`)؛
   بلا سلطة = 403 (اختبار الـHTTP في test_client_report_export).
2. كل تجاوز يُسجَّل في الحارس (`kind="export_override"`) وتُختَم النسخ
   الداخلية «سُلِّمت نسخة عميل بتجاوز مالك — ملاحظات البوابة مرفقة».
3. بوابة نصّ المُنتَج النهائي (`run_client_artifact_text_gate`) تعمل على
   النص الكامل المبني (فقرات + جداول) داخل `render_client_docx` — يغطّي
   مسار PDF لأنه يُبنى منه.

Run: python3 -m pytest tests/test_wp7_delivery_gate_hardening.py -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── ٢) تسجيل التجاوز واستدعاؤه ─────────────────────────────────────────────

def test_override_recorded_and_retrievable(tmp_path, monkeypatch):
    monkeypatch.setenv("SILK_WATCHDOG_DB", str(tmp_path / "wd.db"))
    import silk_watchdog as W
    rec = W.record_override(
        7, "زبدة الفول السوداني", "Kuwait",
        [{"check": "trailing_ellipsis", "note": "بتر", "repairable": False}],
        "docx")
    assert rec and rec["kind"] == "export_override"
    got = W.override_records_for(7)
    assert len(got) == 1
    assert got[0]["gate_findings"][0]["check"] == "trailing_ellipsis"
    assert W.override_records_for(999) == []


def test_internal_copy_stamps_override_history(tmp_path):
    pytest.importorskip("docx")
    from docx import Document
    from silk_render import build_view
    import silk_reports as R
    from tools.canonical_kuwait_peanut_butter import kuwait_research_blob
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(kuwait_research_blob())
    view["test_run"] = True
    view["owner_override_history"] = [{
        "created_at": "2026-07-22T10:00:00",
        "gate_findings": [{"check": "placeholder_leak", "note": "نائب"}]}]
    out = str(tmp_path / "internal.docx")
    R.render_docx(view, out)   # المسار الداخلي (تقرير المدقّق)
    text = "\n".join(p.text for p in Document(out).paragraphs)
    assert "بتجاوز مالك" in text
    assert "placeholder_leak" in text


# ── ٣) بوابة نصّ المُنتَج النهائي ───────────────────────────────────────────

def test_artifact_text_gate_catches_all_leak_classes():
    from silk_quality_gate import run_client_artifact_text_gate as gate
    assert gate("بند تقني غير قابل للعرض المباشر — التفاصيل في أثر التتبع.")
    assert gate("نقطة أولى. إذن ماذا؟ يجب كذا.")
    checks = {f["check"] for f in gate(
        "فقرة تحليلية طويلة بما يكفي تنتهي ببتر واضح هكذا...")}
    assert "trailing_ellipsis" in checks
    contradiction = ("توجد فجوة بيانات في مؤشرات الحوكمة.\n"
                     "لا فجوة جوهرية تمنع اتخاذ القرار.")
    assert any(f["check"] == "gaps_closing_contradiction"
               for f in gate(contradiction))


def test_artifact_text_gate_passes_clean_document_text():
    from silk_quality_gate import run_client_artifact_text_gate as gate
    clean = ("التوصية: مراقبة السوق.\n"
             "الواردات (UN Comtrade) نحو 9 مليون دولار.\n"
             "ماذا يعني هذا لقرارك: ابدأ بملف الأهلية.")
    assert gate(clean) == []
    # سطر عدم التوفّر العام مستثنى هنا (مسار التدهور المتعمَّد للاستدعاء
    # المباشر) — تسليمه عبر API محكوم بفحص القالب client_section_placeholder.
    assert gate("التحليل السردي التفصيلي لهذا القسم غير متاح ضمن هذا "
                "التقرير؛ الأدلة في «المراجع».") == []


def test_render_client_docx_wires_artifact_gate_and_refuses_leak(tmp_path):
    pytest.importorskip("docx")
    from silk_render import build_view
    import silk_reports as R
    from tools.canonical_kuwait_peanut_butter import kuwait_research_blob
    src = open(os.path.join(_ROOT, "silk_reports.py"), encoding="utf-8").read()
    body = src.split("def render_client_docx(")[1].split("\ndef ")[0]
    assert "run_client_artifact_text_gate" in body
    # سلوكياً: حقن بتر «...» في سرد الكاتب => رفض التسليم RuntimeError.
    blob = kuwait_research_blob()
    _txt = blob["deep_research"]["report"]["report"]
    blob["deep_research"]["report"]["report"] = _txt.replace(
        "## 1. الخلاصة التنفيذية\n",
        "## 1. الخلاصة التنفيذية\nفقرة تحليلية طويلة بما يكفي تنتهي ببتر "
        "غير نظيف واضح تماماً...\n", 1)
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(blob)
    view["test_run"] = True
    with pytest.raises(RuntimeError, match="بوابة نصّ المُنتَج النهائي"):
        R.render_client_docx(view, str(tmp_path / "c.docx"))


def test_env_example_documents_owner_key():
    env = open(os.path.join(_ROOT, ".env.example"), encoding="utf-8").read()
    assert "SILK_OWNER_KEY" in env

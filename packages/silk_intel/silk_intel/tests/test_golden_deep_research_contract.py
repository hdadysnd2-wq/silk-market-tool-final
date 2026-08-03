"""الاختبار الذهبي — كل عقود التقرير معاً على سيناريو الحادثة الحية بعينه.

> **الغرض (أمر التثبيت، 2026-07-21، الموجة ٣).** الحوادث الثلاث الحية (بوّابة
> HS المتجاوَزة، تسرّب اليمن↔الكويت، تناقض سعر التجزئة/الجملة) كانت لتُلتَقط
> جميعاً **قبل أن يراها المالك** لو وُجد اختبارٌ واحد يفحص كل العقود معاً على
> نفس سيناريو الحادثة (زبدة الفول السوداني/الكويت) بدل اختباراتٍ مبعثرة كلٌّ
> يفحص عقداً واحداً. هذا الملف ذلك الاختبار — قسمان:
>
>   (أ) **مدوّنة مجمَّدة** (`tools/canonical_kuwait_peanut_butter.py`) —
>       هرمتي بالكامل، بلا شبكة، يفحص عقود طبقة العرض دفعة واحدة: إعادة
>       تأطير HS + تناقض السعر + بادج=متن + صفر تسرّب/سباكة/نائب + وسم التقادُم.
>   (ب) **تدفّق حيّ عبر TestClient** (شبكة محاكاة/بلا شبكة حقيقية — يطابق
>       قيد «الفريز في CI، لا نداء مدفوع حقيقي») — يثبت أن بوّابة HS تحجب
>       *فعلياً* عبر HTTP على /analyze و/research معاً، وأن استئنافاً بسوقٍ
>       آخر يُرفَض بدل تسريب نقاط تفتيش.

Run: python3 -m pytest tests/test_golden_deep_research_contract.py -q
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.canonical_kuwait_peanut_butter import kuwait_research_blob  # noqa: E402

# بصمات اليمن — أيّ ظهورٍ لأيٍّ منها في تقرير الكويت = تسرّبٌ عبر-سوقي (LESSONS ٣٦).
_YEMEN_FINGERPRINTS = ("اليمن", "Yemen", "YEM", "عدن", "ربوع")
# أسماء مزوّدين داخليين يُحظَر ظهورها على أي سطح عميل (LESSONS ١٨).
_VENDOR_FINGERPRINTS = ("Volza", "Explee", "إكسبلي", "فولزا", "Serper", "SerpApi")
_PLACEHOLDER_FINGERPRINTS = ("[شعار سِلك]", "[LOGO]", "[placeholder]")


def _full_text_blob(view: dict) -> str:
    """كل نص العرض مُسطَّحاً بحثاً عن بصمات — json.dumps شامل، لا قسم بعينه."""
    return json.dumps(view, ensure_ascii=False, default=str)


# ══════════════════ (أ) المدوّنة المجمَّدة — عقود طبقة العرض ══════════════════

def test_golden_a_hs_gate_reframing_fired_on_flagged_code():
    """رمزٌ غير مؤكَّد (040510 لزبدة الفول السوداني) => hs_flagged + CONTEXTUAL_TAG
    في الحدود + سقف ثقة الحكم — BUG 1 (إعادة التأطير عند تجاوز البوّابة)."""
    import silk_render as R
    from silk_hs_confirm import CONTEXTUAL_TAG
    dr = R.build_view(kuwait_research_blob())["deep_research"]
    assert dr["hs_flagged"] is True
    assert any(CONTEXTUAL_TAG in l for l in dr["limits"])
    assert dr["concentration_context_only"] is True
    assert dr["verdict"]["confidence"] <= 0.5  # سقف عند التعليم


def test_golden_a_badge_matches_body_no_contradiction():
    """بادج الحكم = لغة المتن — لا «الدخول» في الشارة بينما المتن «مراقبة»."""
    import silk_render as R
    from silk_narrative import verdict_ar
    dr = R.build_view(kuwait_research_blob())["deep_research"]
    badge = dr["verdict_label"]
    v_raw = ((dr["verdict"].get("ai") or {}).get("verdict")
             or dr["verdict"].get("verdict"))
    body = verdict_ar(v_raw)
    assert "مراقبة" in badge and "مراقبة" in body
    assert "الدخول" not in badge


def test_golden_a_price_contradiction_explained_not_fabricated():
    """تناقض 0.67$/كجم (تجزئة) مقابل ~6$/كجم (استيراد كومتريد) — BUG 1.3:
    كلا الرقمين محفوظان كما رُصدا (لا تصحيح/متوسط مختلَق)، وسبب التناقض
    (فئة كومتريد مجاورة) مذكورٌ صراحة في المتن لا مخفياً."""
    import silk_render as R
    dr = R.build_view(kuwait_research_blob())["deep_research"]
    rows = dr["price_rows"]
    values = [r["value"] for r in rows]
    assert any("0.67" in str(v) for v in values), "سعر التجزئة الحقيقي غاب"
    assert any("6" in str(v) for v in values), "سعر الاستيراد/الجملة غاب"
    # كل صفّ يحمل مفتاح سبب (فارغ = قابل للحساب مباشرة، غير فارغ = تعذّر
    # الاشتقاق) — الحقل حاضرٌ دوماً، لا صفّ عارٍ بلا تصنيف (Wave 3.1).
    assert all("reason" in r for r in rows)
    report_text = dr["report"]["text"]
    assert "ليس خطأً" in report_text or "فئة كومتريد مجاورة" in report_text or \
        "مؤشر سياقي" in report_text, (
        "التناقض يجب أن يُفسَّر في المتن — تدهورٌ صامتٌ ممنوع")


def test_golden_a_zero_cross_market_leak_in_kuwait_view():
    """صفر بصمة يمنية في كامل عرض تقرير الكويت — BUG 2 على مستوى المحتوى."""
    import silk_render as R
    view = R.build_view(kuwait_research_blob())
    blob = _full_text_blob(view)
    hits = [fp for fp in _YEMEN_FINGERPRINTS if fp in blob]
    assert not hits, f"تسرّبٌ عبر-سوقي: بصمات يمنية ظهرت في عرض الكويت: {hits}"


def test_golden_a_zero_vendor_names_and_placeholders_and_section_glyph():
    """صفر اسم مزوّد داخلي / نائب مموّه / رمز «§» في متن التقرير النهائي."""
    import silk_render as R
    dr = R.build_view(kuwait_research_blob())["deep_research"]
    text = dr["report"]["text"]
    for fp in _VENDOR_FINGERPRINTS:
        assert fp not in text, f"اسم مزوّد داخلي تسرّب: {fp}"
    for fp in _PLACEHOLDER_FINGERPRINTS:
        assert fp not in text, f"نائبٌ مموّه تسرّب: {fp}"
    assert "§" not in text


def test_golden_a_stale_year_tagged_2021_income_figure():
    """دخل الفرد (2021) يقع خارج نافذة التقادُم الافتراضية (٥ سنوات من
    2026) — يجب أن يظهر ضمن سنوات الحقائق المتقادِمة المُشتقّة بنيوياً."""
    from silk_staleness import stale_fact_years
    ms = kuwait_research_blob()["deep_research"]["missions"]
    allf = [f for v in ms.values() for f in v["findings"]]
    assert 2021 in stale_fact_years(allf)


def test_golden_a_quality_gate_runs_on_this_shape():
    """بوّابة الجودة (silk_quality_gate) تُشغَّل فعلياً على هذا الشكل —
    الأداة نفسها التي أُلحِقت بـ/research الحيّ (Wave 4)."""
    import silk_render as R
    import silk_quality_gate as QG
    view = R.build_view(kuwait_research_blob())
    out = QG.run_quality_gate(view)
    assert "verdict" in out and "findings" in out


# ═══════════════ (ب) تدفّق حيّ عبر TestClient — البوّابة + منع الاستئناف ═══════════════

def _client():
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.app)


def test_golden_b_hs_gate_blocks_kuwait_peanut_butter_on_both_paths_live():
    """نفس منتج/سوق الحادثة الحية بالضبط — كلا /analyze و/research يرفضان
    422 بلا تأكيدٍ صريح، تحت الإعداد الافتراضي (بلا أيّ متغيّر env) — BUG 1
    مُثبَتٌ حياً لا هرمتياً فقط."""
    with patch.dict(os.environ, {"SILK_API_KEY": "secret"}), \
         patch("requests.get", side_effect=OSError("net blocked")):
        client = _client()
        hdr = {"X-API-Key": "secret"}
        r_research = client.post(
            "/research", json={"product": "زبدة الفول السوداني",
                               "market": "Kuwait", "hs_code": "040510",
                               "async_run": False, "persist": False},
            headers=hdr)
        r_analyze = client.post(
            "/analyze", json={"product": "زبدة الفول السوداني",
                              "hs_code": "040510", "persist": False},
            headers=hdr)
    for label, r in (("research", r_research), ("analyze", r_analyze)):
        assert r.status_code == 422, f"{label}: {r.status_code} {r.text}"
        assert r.json()["detail"]["error"] == "hs_confirmation_needed", label


def test_golden_b_resume_of_kuwait_run_as_different_market_is_rejected_live():
    """تشغيلةُ كويت حقيقية (persist=True) لا يمكن استئنافها بسوقٍ آخر —
    BUG 2 مُثبَتٌ حياً على نفس سيناريو الحادثة (اتجاهٌ معكوس: الكويت مصدرٌ،
    سوقٌ آخر طالبٌ — نفس الآلية بالضبط بغضّ النظر عن اتجاه السوقين)."""
    def _fake_call_tools(system, messages, tools=None, max_tokens=1600,
                         model=None, timeout=None):
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(
                {"findings": [], "gaps": [], "summary": "ok"})}]}

    def _fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        return "## 1. خلاصة\nنص"

    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test",
                                 "SILK_API_KEY": "secret"}), \
         patch("silk_llm_runtime._call_tools", side_effect=_fake_call_tools), \
         patch("silk_synthesis._call", side_effect=_fake_call), \
         patch("silk_ai_judge._call", side_effect=_fake_call), \
         patch("silk_storage._db_path", return_value=db):
        client = _client()
        hdr = {"X-API-Key": "secret"}
        r1 = client.post("/research", headers=hdr, json={
            "product": "زبدة الفول السوداني", "market": "Kuwait",
            "hs_code": "040510", "persist": True, "hs_confirmed": True})
        assert r1.status_code == 200, r1.text
        kuwait_id = r1.json()["analysis_id"]

        r2 = client.post("/research", headers=hdr, json={
            "resume": kuwait_id, "market": "Yemen"})
        assert r2.status_code == 409, r2.text
        assert r2.json()["detail"]["error"] == "resume_market_mismatch"

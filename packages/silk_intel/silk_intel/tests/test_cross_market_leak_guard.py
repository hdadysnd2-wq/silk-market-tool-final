"""قفل الانحدار — تسرّب اليمن↔الكويت (البلاغ الحي، 2026-07-21).

الحادثة: تقرير `/research` مسلَّم لسوق **الكويت** حمل بيانات **اليمن**
حرفياً («سوق عدن المركزي»، «ربوع») في قسمَي ثقافة المستهلك والمنافسة —
خرقُ سرّية/صحة (عميلٌ يرى بيانات سوقٍ آخر). التتبّع (مراجعة شيفرة): نقاط
تفتيش البعثات (`research_missions`) كانت تُخزَّن وتُقرأ بمفتاح `analysis_id`
فقط بلا أيّ عمود سوق، واستئناف `/research` كان يسمح لـ`req.market` بتجاوز
سوق التشغيلة المخزَّنة بلا أي تحقّق — فاستئناف مُعرِّف تشغيلة يمن بـ
`market="Kuwait"` يُعيد استهلاك نقاط تفتيش اليمن (`consumer_culture`،
`competitors`) حرفياً في تقريرٍ يُوسَم كويتياً.

الإصلاح (طبقتان — دفاع بعمق):
  ١) بوّابة API: `resume` يرفض (409 `resume_market_mismatch`) حين يطلب
     المستدعي سوقاً يخالف `market_iso3` المخزَّن وقت إنشاء التشغيلة.
  ٢) شبكة أمان بنيوية على المخزن: كل نقطة تفتيش بعثة تُختَم بـ`market_iso3`
     (`silk_storage.save_mission_checkpoint`)، و`load_mission_checkpoints`
     ترفض أيّ صفّ مختوم بسوقٍ آخر عن السوق المطلوب — حتى لو تجاوزت طبقة
     API الأولى بطريقةٍ ما لاحقاً، لا يمكن لبعثة سوقٍ أن تخرج لتقرير سوقٍ آخر.

Run: python3 -m pytest tests/test_cross_market_leak_guard.py -q
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _client():
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.app)


def _fake_call_tools(system, messages, tools=None, max_tokens=1600,
                     model=None, timeout=None):
    return {"stop_reason": "end_turn", "content": [
        {"type": "text", "text": json.dumps(
            {"findings": [], "gaps": [], "summary": "ok"})}]}


def _fake_call(system, user, max_tokens=1600, model=None, timeout=None):
    return "## 1. خلاصة\nنص"


# ══════════════ (١) بوّابة API — رفض استئناف بسوقٍ مختلف ══════════════

def test_resume_with_different_market_is_rejected_409_not_silently_served():
    """تشغيلةُ يمن (persist=True) تُستأنَف لاحقاً بسوق «الكويت» — يُرفَض
    409 `resume_market_mismatch` بدل تشغيل التشغيلة على سوقٍ آخر يحمل
    نقاط تفتيش سوقٍ سابق. هذا بالضبط المسار الذي أنتج الحادثة الحية."""
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
            "product": "زبدة الفول السوداني", "market": "Yemen",
            "hs_code": "200811", "persist": True, "hs_confirmed": True})
        assert r1.status_code == 200, r1.text
        yemen_id = r1.json()["analysis_id"]

        r2 = client.post("/research", headers=hdr, json={
            "resume": yemen_id, "market": "Kuwait"})
        assert r2.status_code == 409, r2.text
        detail = r2.json()["detail"]
        assert detail["error"] == "resume_market_mismatch"
        assert detail["stored_market_iso3"] == "YEM"
        assert detail["requested_market_iso3"] == "KWT"


def test_resume_with_same_market_still_works_no_false_block():
    """استئناف بنفس السوق (أو بلا `market` — يُستنتَج من المخزَّن) يعمل
    كالمعتاد — البوّابة لا تحجب الاستخدام المشروع."""
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
            "product": "تمور", "market": "Nigeria", "hs_code": "080410",
            "persist": True})
        assert r1.status_code == 200, r1.text
        aid = r1.json()["analysis_id"]

        r2 = client.post("/research", headers=hdr,
                         json={"resume": aid, "market": "Nigeria"})
        assert r2.status_code == 200, r2.text
        r3 = client.post("/research", headers=hdr, json={"resume": aid})
        assert r3.status_code == 200, r3.text


# ══════════════ (٢) شبكة أمان بنيوية — مخزن نقاط التفتيش ══════════════

def test_checkpoint_store_rejects_foreign_market_even_if_api_gate_bypassed():
    """اختبارٌ مباشر على `silk_storage` (بلا HTTP): نقطة تفتيش مختومة
    بسوقٍ (اليمن) لا تُعاد أبداً حين تُطلَب لسوقٍ آخر (الكويت) — even إن
    استدعى مسارٌ مستقبليٌّ آخر `load_mission_checkpoints` مباشرةً بلا
    المرور ببوّابة `/research`. تحقّق «صفر بيانات سوقٍ Y في تقرير سوق X»."""
    import silk_storage
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint

    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    yemen_report = AgentReport(
        agent_name="LLMMissionAgent:consumer_culture",
        findings=[DataPoint(value="سوق عدن المركزي / ربوع",
                            source="web_search", confidence=0.6,
                            note="نتيجة بحث")],
        failed=False, summary="ثقافة استهلاك اليمن")

    silk_storage.save_mission_checkpoint(
        1, "consumer_culture", yemen_report, path=db, market_iso3="YEM")

    # طلبٌ بسوق الكويت لا يستلم نقطة تفتيش اليمن إطلاقاً.
    kuwait_view = silk_storage.load_mission_checkpoints(
        1, path=db, market_iso3="KWT")
    assert "consumer_culture" not in kuwait_view, (
        "تسرّب: نقطة تفتيش اليمن أُعيدت لطلبٍ بسوق الكويت")
    all_findings_text = json.dumps(kuwait_view, default=str, ensure_ascii=False)
    assert "عدن" not in all_findings_text and "ربوع" not in all_findings_text

    # نفس السوق يستلمها بلا مشكلة — الفلتر لا يحجب الاستخدام الصحيح.
    yemen_view = silk_storage.load_mission_checkpoints(
        1, path=db, market_iso3="YEM")
    assert "consumer_culture" in yemen_view

    # بلا فلتر (استدعاءٌ قديم بلا market_iso3) — السلوك التاريخي يبقى (لا
    # انحدار على مستدعين لم يُحدَّثوا بعد).
    unfiltered = silk_storage.load_mission_checkpoints(1, path=db)
    assert "consumer_culture" in unfiltered


def test_checkpoint_store_legacy_rows_without_market_tag_are_not_blocked():
    """صفوفٌ قديمة (قبل هذه الميزة، `market_iso3 IS NULL`) لا تُحجَب —
    لا انحدار على تشغيلات محفوظة سابقاً حين يُفعَّل الفلتر لاحقاً."""
    import silk_storage
    from silk_agents import AgentReport

    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    old_report = AgentReport(agent_name="x", findings=[], failed=False,
                             summary="s")
    # محاكاة صفّ قديم: لا market_iso3 (None الافتراضي).
    silk_storage.save_mission_checkpoint(1, "tradeflow", old_report, path=db)
    out = silk_storage.load_mission_checkpoints(1, path=db, market_iso3="KWT")
    assert "tradeflow" in out, "صفٌّ قديم بلا ختم سوق يجب ألا يُحجَب"

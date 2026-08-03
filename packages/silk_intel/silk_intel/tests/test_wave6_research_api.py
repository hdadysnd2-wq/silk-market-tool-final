"""اختبارات الموجة ٤ب (V5): POST /research — البحث العميق كنقطة نهاية.

يغطي: سوق غامض => 422 + اقتراحات (لا تخمين)، مسار كيليسي يعمل بلا 500
(كل شيء يتدهور لفجوات معلنة)، مسار كامل مموّه ينتج حكم مرحلة ٢ وتقريراً
مراجَعاً ويُخزَّن، ونموذج الطلب لا يحمل حقولاً مدفوعة (فحص بنيوي).
Run:  python3 -m pytest tests/ -q
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


def test_ambiguous_market_returns_422_with_suggestions_no_guessing():
    r = _client().post("/research", json={"product": "تمور", "market": "Nigera"})
    assert r.status_code == 422
    body = r.json()["detail"]
    assert "Nigeria" in body["suggestions"]


def test_no_key_returns_409_never_a_silent_skeleton():
    # بلاغ حي (أول تشغيلة إنتاجية): بلا كلود كان /research يسلّم 200 بهيكل
    # فارغ (١٢ بعثة فاشلة، "يتطلب مفتاح كلود") وكأنه المنتج النهائي — الآن
    # يُرفض صراحة بـ409 قبل تشغيل أي بعثة، لا صامتاً بعد التشغيل.
    with patch("requests.get", side_effect=OSError("network disabled")):
        r = _client().post("/research", json={
            "product": "تمور", "market": "Nigeria", "hs_code": "080410",
            "persist": False})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "research_not_ready"
    assert "ANTHROPIC_API_KEY" in detail["reason"]


def test_allow_degraded_escape_hatch_runs_and_stamps_degraded():
    # فتحة الهروب الصريحة: allow_degraded=true يشغّل التشغيلة رغم غياب
    # كلود، لكن يُوسَم الناتج degraded=true بسبب واضح — لا هيكل صامت.
    with patch("requests.get", side_effect=OSError("network disabled")):
        r = _client().post("/research", json={
            "product": "تمور", "market": "Nigeria", "hs_code": "080410",
            "persist": False, "allow_degraded": True})
    assert r.status_code == 200
    data = r.json()
    dr = data["deep_research"]
    assert len(dr["missions"]) == 12
    assert dr["verdict"]["verdict"]  # المرحلة ١ الحتمية تعمل دوماً
    assert dr["report"]["report"] is None  # بلا مفتاح => لا تقرير مختلَق
    assert data["degraded"] is True
    assert "ANTHROPIC_API_KEY" in data["degraded_reason"]
    assert data["view"]["degraded"] is True
    assert data["view"]["deep_research"]["degraded"] is True


def test_full_mocked_run_reaches_stage2_and_writes_report():
    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(
                {"findings": [], "gaps": [], "summary": "ok"})}]}

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        return json.dumps({"verdict": "WATCH", "confidence": 0.5,
                           "reasoning": "ok"})

    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test",
                                 "SILK_API_KEY": "secret"}), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools), \
         patch("silk_synthesis._call", side_effect=fake_call), \
         patch("silk_ai_judge._call", side_effect=fake_call), \
         patch("silk_storage._db_path", return_value=db):
        r = _client().post(
            "/research", headers={"X-API-Key": "secret"},
            json={"product": "تمور", "market": "Nigeria", "hs_code": "080410",
                 "persist": True})

    assert r.status_code == 200
    data = r.json()
    dr = data["deep_research"]
    assert dr["verdict"]["ai"]["verdict"] == "WATCH"
    assert dr["report"]["report"]
    assert data.get("analysis_id") is not None
    assert data["view"]  # القالب الموحّد يُبنى بلا استثناء


def test_request_model_has_no_paid_fields():
    import inspect
    import api

    src = inspect.getsource(api.create_app)
    # فحص خفيف: نموذج ResearchRequest لا يذكر أياً من حقول التعميق المدفوعة.
    # own_price ليس حقلاً مدفوعاً (غير مذكور في _PAID_FLAGS إطلاقاً — رقم
    # سردي حر لحساب الهامش عند المضاهاة داخل المحلل المجاني) فأُزيل من هذه
    # القائمة عمداً (الموجة ٩، بلاغ حي: "الموقع التنافسي" غائب من /research
    # لأن own_price/product_card لم يكونا يصلان الوكلاء إطلاقاً — أُصلح).
    idx = src.find("class ResearchRequest")
    assert idx != -1
    body = src[idx:idx + 800]
    for paid_field in ("with_volza", "with_explee", "with_localprice"):
        assert paid_field not in body


def test_hs_resolved_automatically_when_omitted():
    with patch("requests.get", side_effect=OSError("network disabled")):
        r = _client().post("/research", json={
            "product": "تمور", "market": "Nigeria", "persist": False,
            "allow_degraded": True})
    assert r.status_code == 200
    data = r.json()
    # التمور رمزها الحقيقي 080410 في بذرة سِلك — يُحلّ تلقائياً بلا hs_code صريح.
    assert data["hs_code"] == "080410"

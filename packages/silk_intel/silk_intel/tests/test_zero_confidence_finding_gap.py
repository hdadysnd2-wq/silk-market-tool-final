"""قفل عقد عدم الاختلاق على بنود البعثات — zero-confidence findings lock.

بلاغ حي (حارس المراقبة، تشغيلة زبدة الفول السوداني/الكويت 2026-07-23):
بعثة `demand_trends` شحنت بنداً قيمته غير فارغة (نص الادعاء) بثقة 0.0 —
الزوج المتناقض الذي يحرّمه العقد التأسيسي (إما قيمة بثقة حقيقية أو فجوة
None/0.0 كاملة، لا مزيج). المصدر: حلقة القبول في
`silk_llm_runtime._parse_output` كانت تقصّ الثقة إلى [0,1] وتُبقي البند
حتى لو صرّح النموذج بثقة 0.0، أو ورثها `min()` من نقطة بيانات فجوة
مستشهَد بها (ثقتها 0.0 بحكم العقد — حالة FAOSTAT 401 في التشغيلة الحية).

القانون: **ادعاء بثقة صفرية ليس بنداً — إنه فجوة تُعلَن**: يُنقَل نصه إلى
`gaps` ويُسجَّل في `dropped` بسبب معلن، ولا يدخل `findings` أبداً.

هرمتي بالكامل — `_parse_output` دالة نقية (نص + سجل نقاط)، لا شبكة.
Run: python3 -m pytest tests/test_zero_confidence_finding_gap.py -q
"""
import json

import silk_llm_runtime as rt
import silk_watchdog
from silk_data_layer import DataPoint


def _registry() -> dict:
    """سجل نقاط مستشهَد بها: واحدة سليمة وواحدة فجوة معلنة (عقد العقد:
    value=None بثقة 0.0 — شكل فشل FAOSTAT 401 في التشغيلة الحية)."""
    return {
        "dp1": DataPoint(63.0, "Google Trends", 0.8,
                         "متوسط اهتمام البحث 5 سنوات", "2026-07-23"),
        "gap1": DataPoint(None, "FAOSTAT", 0.0,
                          "401 Unauthorized — فجوة معلنة", "2026-07-23"),
    }


def _final(findings: list[dict]) -> str:
    return json.dumps({"findings": findings, "gaps": [], "summary": "س"},
                      ensure_ascii=False)


def test_model_stated_zero_confidence_claim_becomes_declared_gap():
    """النموذج يصرّح بثقة 0.0 لادعاء غير فارغ => لا بند؛ فجوة معلنة + إسقاط
    مسبَّب — لا زوج (قيمة، 0.0) يُشحَن أبداً."""
    out = rt._parse_output(_final([
        {"claim": "الطلب الموسمي أعلى من السنوي",
         "datapoint_ids": ["dp1"], "confidence": 0.0}]), _registry())
    assert out["findings"] == []
    assert any("الطلب الموسمي أعلى من السنوي" in g for g in out["gaps"])
    assert out["dropped"] and "zero-confidence" in out["dropped"][0]["reason"]


def test_inherited_zero_confidence_from_cited_gap_datapoint_not_shipped():
    """ثقة غير قابلة للقراءة => تُورَث `min()` من النقاط المستشهَد بها؛
    الاستشهاد بنقطة فجوة (ثقة 0.0) كان يورث 0.0 ويُبقي البند — حالة
    demand_trends الحية بالضبط. يجب أن تصير فجوة معلنة."""
    out = rt._parse_output(_final([
        {"claim": "بيانات نصيب الفرد من FAOSTAT غير متاحة",
         "datapoint_ids": ["gap1"], "confidence": "غير رقم"}]), _registry())
    assert out["findings"] == []
    assert any("FAOSTAT" in g for g in out["gaps"])


def test_rounding_to_zero_is_also_a_gap():
    """ثقة موجبة تافهة تُقرَّب لـ0.0 (round(0.004, 2)) — نفس الزوج المتناقض
    بعد التقريب، نفس المصير: فجوة معلنة لا بند."""
    out = rt._parse_output(_final([
        {"claim": "إشارة ضعيفة جداً", "datapoint_ids": ["dp1"],
         "confidence": 0.004}]), _registry())
    assert out["findings"] == []


def test_real_confidence_finding_still_kept():
    """البند السليم (ثقة حقيقية) يمرّ كما كان — القفل لا يُفرِغ البعثات."""
    out = rt._parse_output(_final([
        {"claim": "اتجاه خمس سنوات صاعد", "datapoint_ids": ["dp1"],
         "confidence": 0.75}]), _registry())
    assert len(out["findings"]) == 1
    assert out["findings"][0]["confidence"] == 0.75
    assert out["gaps"] == []


def test_watchdog_no_fabrication_holds_on_parse_output_shape():
    """التكامل مع الحارس: بنود ناجية من `_parse_output` مُسلسَلة بشكل
    `dr["missions"]` (dataclasses.asdict على DataPoint) يجب ألّا تُحمِّر
    `_check_no_fabrication` — الخرق الحي يستحيل بنيوياً بعد القفل."""
    reg = _registry()
    out = rt._parse_output(_final([
        {"claim": "اتجاه صاعد", "datapoint_ids": ["dp1"], "confidence": 0.7},
        {"claim": "ادعاء صفري الثقة", "datapoint_ids": ["gap1"],
         "confidence": 0.0}]), reg)
    findings = [{"value": f["claim"], "source": "Google Trends",
                 "confidence": f["confidence"], "note": ""}
                for f in out["findings"]]
    dr = {"missions": {"demand_trends": {"findings": findings}}}
    status, alerts = silk_watchdog._check_no_fabrication(dr)
    assert status["status"] == "held", status
    assert alerts == []

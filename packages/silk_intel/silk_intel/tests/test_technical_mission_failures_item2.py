"""إصلاح البند ٢ (تدقيق حيّ، تمور/هولندا) — إغلاق الأعطال التقنية فقط، لا
الفجوات المعلنة الأصيلة:

(a) بعثة الأخبار والمخاطر: نداء حوكمة البنك الدولي (WGI) كان يفشل بخطأ
    "قيمة معامل" — الإصلاح موجود فعلاً في الشيفرة (source=3 لمؤشرات WGI،
    silk_data_layer._WB_INDICATOR_SOURCE) لكن بلا اختبار يتحقّق من *الطلب*
    نفسه (الاختبارات القائمة تُموِّه _cached_get فتتحقّق من التفسير فقط، لا
    من أن source=3 أُرسِل فعلاً) — هذا الملف يسدّ تلك الفجوة الاختبارية.

(b) بعثة الفرص الاستراتيجية (opportunity_gaps) + الطبقة ٣ SWOT: فشل تفسير
    JSON نهائي كان يستسلم فوراً بفجوة معلنة بلا أي محاولة تصحيح. الإصلاح:
    محاولة إصلاح واحدة (silk_llm_runtime._JSON_REPAIR_NUDGE) — لا حلقة،
    فشلها أيضاً يبقى فجوة معلنة كالسابق.

(c) بعثة اتجاهات الطلب: استعلام openalex_search بالاسم العربي/مزيج ضيّق لم
    يُطابِق فهرس OpenAlex الأدبي الإنجليزي غالباً — تعليمات البعثة الآن
    توجّه لمصطلحات إنجليزية عامة، مع تصريح أن نتيجة فارغة حقيقية بعدها
    فجوة معلنة لا عطل.

Run: python3 -m pytest tests/test_technical_mission_failures_item2.py -q
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network


def _ref():
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Netherlands")
    return ref


# ── (a) WGI source=3 — تحقّق من الطلب الفعلي لا التفسير فقط ────────────────

def test_wgi_indicator_request_carries_source_3_param():
    import silk_data_layer as DL
    captured = {}

    def fake_cached_get(url, params, ttl_seconds=86400):
        captured["params"] = dict(params)
        return [{"page": 1, "pages": 1, "per_page": "100", "total": 1},
               [{"indicator": {"id": "X"}, "country": {"id": "XX"},
                 "date": "2022", "value": 1.18, "unit": "",
                 "obs_status": "", "decimal": 0}]]

    with patch.object(DL, "_cached_get", side_effect=fake_cached_get):
        dp = DL.world_bank("NLD", "PV.EST")
    assert captured["params"].get("source") == "3", (
        "بلاغ حي: خطأ 'قيمة معامل' من واجهة WGI يعني عدم وصول source=3 "
        f"فعلياً في الطلب — params أُرسلت: {captured['params']}")
    assert dp.value == 1.18


def test_non_wgi_indicator_request_omits_source_param():
    """لا انحدار: مؤشرات غير WGI (سكان/دخل) تبقى بلا معامل source إطلاقاً —
    البنك الدولي يرفض معاملاً غير متوقَّع لبعض المؤشرات."""
    import silk_data_layer as DL
    captured = {}

    def fake_cached_get(url, params, ttl_seconds=86400):
        captured["params"] = dict(params)
        return [{"page": 1, "pages": 1, "per_page": "100", "total": 1},
               [{"indicator": {"id": "X"}, "country": {"id": "XX"},
                 "date": "2022", "value": 17_900_000.0, "unit": "",
                 "obs_status": "", "decimal": 0}]]

    with patch.object(DL, "_cached_get", side_effect=fake_cached_get):
        DL.world_bank("NLD", "SP.POP.TOTL")
    assert "source" not in captured["params"]


def test_all_six_wgi_codes_map_to_source_3():
    """مصفوفة تثبيت لكل الرموز الستة الموسومة WGI — لا كود منسيّ يتراجع
    صامتاً للمصدر الافتراضي (source=2 المؤرشف)."""
    import silk_data_layer as DL
    for code in ("PV.EST", "RL.EST", "RQ.EST", "GE.EST", "CC.EST", "VA.EST"):
        captured = {}

        def fake_cached_get(url, params, ttl_seconds=86400, _c=captured):
            _c["params"] = dict(params)
            return [{"page": 1}, [{"date": "2022", "value": 0.1}]]

        with patch.object(DL, "_cached_get", side_effect=fake_cached_get):
            DL.world_bank("NLD", code)
        assert captured["params"].get("source") == "3", code


# ── (b) محاولة إصلاح JSON واحدة ────────────────────────────────────────────

_TOOLLESS_MISSION = {"key": "opportunity_gaps", "name": "الفرص الاستراتيجية",
                     "instructions": "اختبار", "allowed_tools": []}


def _run(fake_call_tools):
    import silk_llm_runtime as rt
    ctx = {"market": _ref(), "product": "تمور", "hs_code": "080410",
          "extra_findings": [], "extra_context": ""}
    with block_network(), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools):
        return rt._run_loop(_TOOLLESS_MISSION, ctx, rt._DEFAULT_BUDGET)


def test_json_repair_retry_recovers_from_malformed_final_answer():
    calls = {"n": 0}

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        calls["n"] += 1
        if calls["n"] <= 2:  # الجولة الأولى + جولة الإنهاء القسري — كلاهما مشوَّه
            return {"stop_reason": "end_turn", "content": [
                {"type": "text", "text": "هذا ليس JSON على الإطلاق، مجرّد نثر."}]}
        # محاولة الإصلاح (النداء الثالث) — JSON صالح هذه المرّة.
        final = {"findings": [{"claim": "أُصلِح", "datapoint_ids": [],
                              "confidence": 0.6}],
                "gaps": [], "summary": "بعد الإصلاح"}
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(final, ensure_ascii=False)}]}

    result = _run(fake_call_tools)
    assert calls["n"] == 3, "يجب بالضبط ثلاثة نداءات: أولى + إنهاء قسري + إصلاح واحد"
    assert result["gaps"] != ["رد كلود غير قابل للتفسير كـ JSON"]
    assert result["summary"] == "بعد الإصلاح"


def test_json_repair_retry_stays_declared_gap_when_repair_also_fails():
    calls = {"n": 0}

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        calls["n"] += 1
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": "لا يزال نثراً غير قابل للتفسير حتى بعد التذكير."}]}

    result = _run(fake_call_tools)
    # ثلاثة نداءات فقط (لا حلقة إصلاح لا نهائية): أولى + إنهاء قسري + إصلاح واحد.
    assert calls["n"] == 3
    assert result["gaps"] == ["رد كلود غير قابل للتفسير كـ JSON"]
    assert result["findings"] == []  # لا اختلاق مهما تكرّر الفشل


def test_json_repair_not_triggered_for_legitimately_empty_findings():
    """لا يُستدعى إصلاح إطلاقاً حين يكون JSON صالحاً تماماً لكن النتائج
    فارغة أصالةً (لا عطل تفسير) — فرق بين فجوة أصيلة وعطل تقني."""
    calls = {"n": 0}

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        calls["n"] += 1
        final = {"findings": [], "gaps": ["لا بيانات فعلية متاحة لهذا السوق"],
                "summary": ""}
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(final, ensure_ascii=False)}]}

    result = _run(fake_call_tools)
    assert calls["n"] == 1, "JSON صالح من أول نداء — لا إنهاء قسري ولا إصلاح"
    assert result["gaps"] == ["لا بيانات فعلية متاحة لهذا السوق"]


# ── (c) توجيه استعلام openalex_search بالإنجليزية + تصريح الفجوة ──────────

def test_demand_trends_instructs_english_openalex_query_and_honest_gap():
    import silk_missions
    txt = silk_missions.MISSIONS["demand_trends"]["instructions"]
    assert "استعلِم بمصطلحات إنجليزية" in txt
    assert "لا الاسم العربي" in txt
    assert "فجوة معلنة، لا" in txt and "عطلاً تقنياً" in txt

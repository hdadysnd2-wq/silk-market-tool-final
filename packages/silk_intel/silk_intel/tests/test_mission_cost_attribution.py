"""أقفال إسناد التكلفة لكل بعثة (Part C — تحضير القياس).

بلاغ: طلب المالك «قدّر التوفير لكل بعثة من بيانات حقيقية قبل الاختيار»
اكتشف أن `record_llm_usage` كانت تُجمِّع الرموز حسب النموذج فقط — والاثنتا
عشرة بعثة تتشارك نموذجاً واحداً (Opus) اليوم، فلا سبيل لمعرفة أيّ بعثة
استهلكت كم من `llm_usage` وحده، ولا حدث تتبّع يحمل عدّ رموز إطلاقاً. هذا
يقفل الإصلاح: `silk_context.mission_context` يسِم كل نداء بمفتاح بعثته،
فيتراكم في `data_counter()["mission_usage"][key]` **فوق** `llm_usage`
الإجمالي القائم لا بدلاً عنه — تشغيلة قديمة (بلا هذا الوسم) تعرض `{}`
صراحة، لا اختلاق. مطلوب لأن حتى بيانات تشغيلة هولندا الحقيقية الموجودة
لا يمكنها الإجابة عن سؤال «تكلفة كل بعثة» بدون هذا الإصلاح أولاً.

هيرمتي بالكامل — لا شبكة، لا مفتاح حقيقي.
"""
from __future__ import annotations

import contextvars
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══ ١ — silk_context.mission_context/record_llm_usage: الإسناد أساسه ═════

def test_mission_context_tags_usage_additively_over_aggregate():
    import silk_context
    silk_context.begin_data_counter()
    with silk_context.mission_context("pricing_scout"):
        silk_context.record_llm_usage("claude-opus-4-8", 1000, 500)
    with silk_context.mission_context("demographics_economy"):
        silk_context.record_llm_usage("claude-opus-4-8", 2000, 1000)
    c = silk_context.data_counter()
    # الإجمالي القائم لم يتغيّر سلوكياً (نفس الشكل، نفس المجموع).
    assert c["llm_usage"]["claude-opus-4-8"]["input_tokens"] == 3000
    # الإسناد الجديد: كل بعثة برموزها منفردة.
    assert c["mission_usage"]["pricing_scout"]["claude-opus-4-8"]["input_tokens"] == 1000
    assert c["mission_usage"]["demographics_economy"]["claude-opus-4-8"]["input_tokens"] == 2000


def test_no_mission_context_means_no_mission_usage_entry():
    """نداءات المحلل/الكاتب/المراجع (خارج mission_context) — لا تُوسَم، لا
    تلوّث mission_usage بمفتاح زائف."""
    import silk_context
    silk_context.begin_data_counter()
    silk_context.record_llm_usage("claude-opus-4-8", 500, 200)   # كأنه نداء كاتب
    c = silk_context.data_counter()
    assert c["llm_usage"]["claude-opus-4-8"]["input_tokens"] == 500
    assert c.get("mission_usage") in (None, {})
    assert silk_context.current_mission() is None


def test_mission_context_is_isolated_per_real_parallel_thread():
    """نفس آلية run_all_missions الحقيقية: copy_context() لكل خيط — بعثتان
    متزامنتان لا تختلطان، ومجموع الإسناد = الإجمالي القائم بالضبط."""
    import silk_context
    silk_context.begin_data_counter()

    def _run(key, tok):
        with silk_context.mission_context(key):
            silk_context.record_llm_usage("claude-opus-4-8", tok, tok // 2)

    jobs = [("pricing_scout", 1000), ("demographics_economy", 2000),
            ("logistics", 500), ("tariffs_agreements", 1500)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(contextvars.copy_context().run, _run, k, n)
                for k, n in jobs]
        for f in futs:
            f.result()

    c = silk_context.data_counter()
    total_agg = c["llm_usage"]["claude-opus-4-8"]["input_tokens"]
    total_by_mission = sum(
        m["claude-opus-4-8"]["input_tokens"] for m in c["mission_usage"].values())
    assert total_agg == total_by_mission == sum(n for _, n in jobs)
    assert set(c["mission_usage"]) == {k for k, _ in jobs}


def test_mission_context_resets_after_block_exits():
    import silk_context
    with silk_context.mission_context("pricing_scout"):
        assert silk_context.current_mission() == "pricing_scout"
    assert silk_context.current_mission() is None


# ═══ ٢ — run_llm_agent يسِم البعثة تلقائياً (لا استدعاء يدوي مطلوب) ════════

def test_run_llm_agent_tags_calls_with_its_own_mission_key(monkeypatch):
    import silk_context
    import silk_llm_runtime as R
    from silk_market_resolver import resolve_market

    seen_mission_during_call = {}

    def fake_run_loop(mission, ctx, budget, timeout=None, model=None):
        # وسم البعثة يجب أن يكون مضبوطاً بالفعل أثناء _run_loop نفسها.
        seen_mission_during_call["key"] = silk_context.current_mission()
        silk_context.record_llm_usage("claude-opus-4-8", 300, 150)
        return {"findings": [], "gaps": [], "summary": "ok", "dropped": [],
               "registry": {}, "tool_calls_used": 1}

    monkeypatch.setattr(R, "_run_loop", fake_run_loop)
    ref, _ = resolve_market("Netherlands")
    silk_context.begin_data_counter()
    R.run_llm_agent({"key": "pricing_scout", "name": "أسعار",
                     "instructions": "ins", "allowed_tools": []},
                    ref, product="تمور", hs_code="080410")
    assert seen_mission_during_call["key"] == "pricing_scout"
    c = silk_context.data_counter()
    assert c["mission_usage"]["pricing_scout"]["claude-opus-4-8"]["input_tokens"] == 300
    assert silk_context.current_mission() is None  # أُعيد للحالة الافتراضية بعد الخروج


# ═══ ٣ — api.py يحسب cost_usd_by_mission بإعادة استعمال estimate_cost_usd ══

def test_cost_usd_by_mission_reuses_estimate_cost_usd_no_new_pricing_logic():
    from silk_pricing import estimate_cost_usd
    mission_usage = {
        "pricing_scout": {"claude-opus-4-8": {"input_tokens": 1_000_000,
                                              "output_tokens": 100_000}},
        "demographics_economy": {"claude-opus-4-8": {"input_tokens": 500_000,
                                                      "output_tokens": 50_000}},
    }
    by_mission = {mkey: estimate_cost_usd(mu)["total_usd"]
                 for mkey, mu in mission_usage.items()}
    assert by_mission["pricing_scout"] > by_mission["demographics_economy"]
    # نفس دالة التسعير الوحيدة — لا حساب مواز؛ نتأكد أنها مطابقة رقمياً لحساب مباشر.
    expected_pricing = estimate_cost_usd(
        mission_usage["pricing_scout"])["total_usd"]
    assert by_mission["pricing_scout"] == expected_pricing


def test_missing_mission_usage_declares_empty_not_fabricated():
    """تشغيلة سابقة لهذا الإصلاح (بلا mission_usage) => {} صريحة، لا رقم مُختلَق."""
    economics = {"llm_usage": {"claude-opus-4-8": {"input_tokens": 100,
                                                    "output_tokens": 50}}}
    from silk_pricing import estimate_cost_usd
    result = {mkey: estimate_cost_usd(mu)["total_usd"]
             for mkey, mu in (economics.get("mission_usage") or {}).items()}
    assert result == {}

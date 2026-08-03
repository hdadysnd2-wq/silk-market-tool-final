"""قياس تكلفة صادق — honest cost metering (close the reporting blind spots).

يغطّي إصلاحين لا يغيّران سلوك الإنفاق، فقط صدق التبليغ:
1. `silk_pricing.estimate_cost_usd` كان يُسقِط النماذج غير المُسعَّرة من
   المجموع بصمت (total_usd أقل من الواقع). الآن يُظهِر رموزها المرصودة في
   `unpriced_tokens` ويضع `complete=False` — بلا تخمين سعر (لا اختلاق).
2. نداءات كلود خارج حلقة البعثات (الكاتب/المراجع/التوليف/الإضافات المجانية)
   كانت غير محسوبة في `data_economics.llm_calls`. الآن `silk_ai_judge._call`
   يعدّ النجاح فقط — آمن للسقف لأن الذيل يعمل بعد انتهاء حلقة البعثات.
"""
from __future__ import annotations

from unittest import mock

import silk_context
import silk_pricing as pricing


# ── الإصلاح ١: صدق تقدير التكلفة ─────────────────────────────────────────

def test_unpriced_model_surfaces_observed_tokens_not_a_guessed_price():
    out = pricing.estimate_cost_usd(
        {"some-future-model": {"input_tokens": 1234, "output_tokens": 567}})
    # لا سعر مُختلَق — الدولار صفر والنموذج معلَن.
    assert out["total_usd"] == 0.0
    assert out["unpriced_models"] == ["some-future-model"]
    assert out["by_model"] == {}
    # لكن الرموز مرصودة تُعرَض، والاكتمال معلَن كاذباً — النقطة العمياء مُغلَقة.
    assert out["unpriced_tokens"] == {
        "some-future-model": {"input_tokens": 1234, "output_tokens": 567}}
    assert out["complete"] is False


def test_all_priced_models_report_complete_true_and_no_unpriced_tokens():
    out = pricing.estimate_cost_usd(
        {"claude-opus-4-8": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}})
    assert out["total_usd"] == 30.0
    assert out["complete"] is True
    assert out["unpriced_tokens"] == {}


def test_mixed_priced_and_unpriced_keeps_dollar_honest_but_flags_incomplete():
    out = pricing.estimate_cost_usd({
        "claude-opus-4-8": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
        "mystery-model": {"input_tokens": 100, "output_tokens": 50}})
    # الدولار يشمل المُسعَّر فقط — صادق، غير مُلوَّث برقم مُخترَع.
    assert out["total_usd"] == 30.0
    assert out["by_model"] == {"claude-opus-4-8": 30.0}
    # الناقص معلَن بوضوح.
    assert out["complete"] is False
    assert out["unpriced_tokens"]["mystery-model"] == {
        "input_tokens": 100, "output_tokens": 50}


def test_engine_economics_surfaces_completeness_and_unpriced_tokens():
    import silk_engine
    c = silk_context.begin_data_counter()
    silk_context.record_llm_usage("claude-opus-4-8", 1_000_000, 1_000_000)
    silk_context.record_llm_usage("mystery-model", 200, 100)
    econ = silk_engine._economics(c)
    assert econ["cost_usd_estimate"] == 30.0        # المُسعَّر فقط
    assert econ["cost_estimate_complete"] is False   # الناقص معلَن
    assert econ["cost_unpriced_models"] == ["mystery-model"]
    assert econ["cost_unpriced_tokens"]["mystery-model"] == {
        "input_tokens": 200, "output_tokens": 100}


# ── الإصلاح ٢: عدّ نداءات الذيل ──────────────────────────────────────────

def _stub_provider(returns):
    prov = mock.Mock()
    prov.complete.return_value = returns
    return mock.patch("silk_llm_provider.get_provider", return_value=prov)


def test_successful_tail_call_is_counted_in_data_economics():
    import silk_ai_judge
    silk_context.begin_data_counter()
    with _stub_provider("a real answer"):
        out = silk_ai_judge._call("sys", "user")
    assert out == "a real answer"
    assert silk_context.data_counter()["llm_calls"] == 1


def test_failed_tail_call_is_not_counted():
    import silk_ai_judge
    silk_context.begin_data_counter()
    with _stub_provider(None):
        out = silk_ai_judge._call("sys", "user")
    assert out is None
    # فشل النداء (None) لا يُعَدّ — نعدّ النجاح فقط.
    assert silk_context.data_counter()["llm_calls"] == 0


def test_tail_call_counting_is_noop_without_an_active_counter():
    import silk_ai_judge
    silk_context._data_counter.set(None)
    with _stub_provider("ok"):
        out = silk_ai_judge._call("sys", "user")
    assert out == "ok"                               # لا انفجار بلا عدّاد
    assert silk_context.data_counter() is None

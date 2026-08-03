"""اختبارات تدقيق المعمارية بعد الموجة ١١ (wave 12) — إغلاق ديون محدَّدة:

1) محور حسابي مدرِك للمعادلات في `silk_evals.citation_correctness_score` —
   رقم مشتق (TAM/SAM/SOM) لا يُسقَط كاختلاق إن كانت مدخلات معادلته مسندة.
2) محوّل مزوّد كلود الرقيق (`LLMProvider`) — سلوك مطابق تماماً لِـ`_call`
   المباشر، تبديل صرف فحسب.
3) تدرّج التكلفة — تقدير دولاري لكل تشغيلة يُضاف لِـ`data_economics`.

لا شبكة ولا مفتاح مطلوبان لأي اختبار هنا (نفس تقليد المستودع الهيرمتي).
Run:  python3 -m pytest tests/test_wave12_architecture_audit.py -q
"""
import contextlib
import os
import sys
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.contextmanager
def _env(**vals):
    """اضبط متغيرات بيئة مع استرجاع مضمون — نفس نمط test_project_review_fixes."""
    old = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── ١: المحور الحسابي (TAM/SAM/SOM) — عينة إسبانيا ──────────────────────────

def _spain_mission_reports():
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    return {
        "trade_flow": AgentReport(
            "LLMAgent:trade_flow",
            [DataPoint("إجمالي واردات إسبانيا من التمور (HS 080410) عام 2022 "
                      "بلغ 33,000,000 دولار", "UN Comtrade", 0.9,
                      "مبني على: تدفق واردات ESP")],
            False, "ok"),
    }


_SPAIN_TAM_SAM_SOM_REPORT = (
    "## 6. حجم السوق — TAM/SAM/SOM\n"
    "TAM = 33,000,000 دولار (إجمالي واردات إسبانيا من التمور HS 080410 عام "
    "2022 — UN Comtrade).\n"
    "SAM = 33,000,000 × 15% (افتراض حصة شريحة التمور الفاخرة من السوق "
    "الكلي) = 4,950,000 دولار.\n"
    "SOM = 4,950,000 × 5% (افتراض حصة واقعية مستهدفة خلال أول ثلاث سنوات) "
    "= 247,500 دولار.\n"
)


def test_tam_sam_som_derived_numbers_are_not_flagged_as_fabrication():
    import silk_evals as ev

    out = ev.citation_correctness_score(_SPAIN_TAM_SAM_SOM_REPORT,
                                        _spain_mission_reports())
    assert out["score"] == 100, out["violations"]
    assert 4950000.0 in out["formula_grounded"]
    assert 247500.0 in out["formula_grounded"]


def test_formula_aware_check_still_rejects_a_fabricated_result():
    import silk_evals as ev

    # الناتج المعلن (9,999,999) لا يطابق حاصل الضرب الفعلي (4,950,000) —
    # يجب أن يُرفض رغم أنه يشبه معادلة TAM/SAM.
    bad = ("TAM = 33,000,000 دولار.\n"
          "SAM = 33,000,000 × 15% (افتراض) = 9,999,999 دولار.\n")
    out = ev.citation_correctness_score(bad, _spain_mission_reports())
    assert out["score"] == 0
    assert 9999999.0 in out["violations"]


def test_formula_aware_check_rejects_equation_with_no_real_grounding():
    import silk_evals as ev

    # كلا الطرفين افتراض بلا رقم حقيقي واحد مسند — لا يجوز قبول السلسلة
    # كاملة من لا شيء (يمنع تبييض رقم مختلَق عبر "معادلة" وهمية).
    ungrounded = ("لنفترض حصة 40% × نفترض 20% (كلاهما افتراض) = 8%.\n")
    out = ev.citation_correctness_score(ungrounded, _spain_mission_reports())
    assert 8.0 in out["violations"]
    assert 8.0 not in out["formula_grounded"]


def test_formula_grounded_numbers_helper_is_directly_callable():
    import silk_evals as ev

    known = {33000000.0}
    grounded = ev.formula_grounded_numbers(_SPAIN_TAM_SAM_SOM_REPORT, known)
    # ناتجا TAM/SAM المشتقّان + نسبتا الافتراض المُعلَنتان صراحة (15%، 5%).
    assert grounded == {4950000.0, 247500.0, 15.0, 5.0}


# ── ٢: محوّل المزوّد الرقيق (`silk_llm_provider`) — دين ٣ ───────────────────

def test_get_provider_defaults_to_anthropic():
    import silk_llm_provider as lp

    lp.reset_provider()
    try:
        with _env(SILK_LLM_PROVIDER=None):
            assert isinstance(lp.get_provider(), lp.AnthropicProvider)
    finally:
        lp.reset_provider()


def test_get_provider_falls_back_to_anthropic_for_unknown_name():
    import silk_llm_provider as lp

    lp.reset_provider()
    try:
        with _env(SILK_LLM_PROVIDER="not-a-real-provider"):
            assert isinstance(lp.get_provider(), lp.AnthropicProvider)
    finally:
        lp.reset_provider()


def test_get_provider_is_a_cached_singleton():
    import silk_llm_provider as lp

    lp.reset_provider()
    try:
        assert lp.get_provider() is lp.get_provider()
    finally:
        lp.reset_provider()


def test_anthropic_provider_complete_returns_none_without_key():
    import silk_llm_provider as lp

    with _env(ANTHROPIC_API_KEY=None):
        out = lp.AnthropicProvider().complete("sys", "user", 100, "m", 5)
    assert out is None


def test_anthropic_provider_complete_tools_returns_none_without_key():
    import silk_llm_provider as lp

    with _env(ANTHROPIC_API_KEY=None):
        out = lp.AnthropicProvider().complete_tools("sys", [], None, 100, "m", 5)
    assert out is None


def test_ai_judge_call_delegates_to_provider_unchanged_behavior():
    """`silk_ai_judge._call` يجب أن يفوّض لـ`get_provider().complete` بنفس
    الوسائط ويُعيد نفس النتيجة — لا تغيّر سلوكي عن التنفيذ المباشر السابق."""
    import silk_ai_judge as judge

    captured = {}

    class _FakeProvider:
        def complete(self, system, user, max_tokens, model, timeout):
            captured.update(system=system, user=user, max_tokens=max_tokens,
                           model=model, timeout=timeout)
            return "الرد المتوقَّع"

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_llm_provider.get_provider", return_value=_FakeProvider()):
        out = judge._call("سياق", "سؤال", max_tokens=42, model="m-x", timeout=9)
    assert out == "الرد المتوقَّع"
    assert captured == {"system": "سياق", "user": "سؤال", "max_tokens": 42,
                        "model": "m-x", "timeout": 9}


def test_ai_judge_call_tools_delegates_to_provider_unchanged_behavior():
    import silk_ai_judge as judge

    captured = {}

    class _FakeProvider:
        def complete_tools(self, system, messages, tools, max_tokens, model, timeout):
            captured.update(system=system, messages=messages, tools=tools,
                           max_tokens=max_tokens, model=model, timeout=timeout)
            return {"stop_reason": "end_turn", "content": []}

    msgs = [{"role": "user", "content": "hi"}]
    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_llm_provider.get_provider", return_value=_FakeProvider()):
        out = judge._call_tools("سياق", msgs, tools=[{"name": "t"}],
                                max_tokens=7, model="m-y", timeout=3)
    assert out == {"stop_reason": "end_turn", "content": []}
    assert captured["messages"] is msgs
    assert captured["model"] == "m-y"


def test_ai_judge_call_still_respects_ai_extras_block_before_provider():
    """الحجب السياقي يبقى مسؤولية `silk_ai_judge` (سياسة) لا `silk_llm_provider`
    (آلية HTTP) — نداء المزوّد يجب ألا يُستدعى أصلاً حين محجوب."""
    import silk_ai_judge as judge

    called = {"n": 0}

    class _FakeProvider:
        def complete(self, *a, **k):
            called["n"] += 1
            return "should not happen"

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_context.ai_extras_blocked", return_value=True), \
         patch("silk_llm_provider.get_provider", return_value=_FakeProvider()):
        out = judge._call("سياق", "سؤال")
    assert out is None
    assert called["n"] == 0


def test_anthropic_provider_complete_matches_prior_inline_behavior_on_success():
    """محاكاة استجابة Anthropic حقيقية — يتحقق أن الاستخراج (نص/رفض) يطابق
    ما كان `_call` يفعله قبل الاستخراج إلى silk_llm_provider حرفياً."""
    import silk_llm_provider as lp

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "مرحباً"}]}

    with _env(ANTHROPIC_API_KEY="test-key"), \
         mock.patch("requests.post", return_value=_Resp()):
        out = lp.AnthropicProvider().complete("sys", "user", 100, "m", 5)
    assert out == "مرحباً"


def test_anthropic_provider_complete_returns_none_on_refusal():
    import silk_llm_provider as lp

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "refusal", "content": []}

    with _env(ANTHROPIC_API_KEY="test-key"), \
         mock.patch("requests.post", return_value=_Resp()):
        out = lp.AnthropicProvider().complete("sys", "user", 100, "m", 5)
    assert out is None


# ── ٣: تدرّج التكلفة + تقدير التكلفة (silk_pricing) — دين ٤ ─────────────────

def test_reviewer_already_uses_fast_model_regression_guard():
    """حارس انحدار: المراجع (review_report) يجب أن يبقى على _FAST_MODEL —
    لا يجوز أن يعود يستخدم النموذج الرئيسي الأبطأ/الأغلى صمتاً."""
    import inspect

    import silk_ai_judge as judge

    src = inspect.getsource(judge.review_report)
    assert "model=_FAST_MODEL" in src or "model=judge._FAST_MODEL" in src


def test_quality_gate_makes_zero_llm_calls():
    """بوابة الجودة حتمية بالكامل — لا نداء كلود فيها (لا شيء يحتاج تدرّجاً)."""
    import inspect

    import silk_quality_gate as qg

    src = inspect.getsource(qg)
    assert "silk_ai_judge._call(" not in src
    assert "_FAST_MODEL" not in src and "_MODEL" not in src


def test_pricing_estimates_known_models():
    import silk_pricing as pricing

    usage = {"claude-opus-4-8": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
             "claude-haiku-4-5-20251001": {"input_tokens": 1_000_000,
                                          "output_tokens": 1_000_000}}
    out = pricing.estimate_cost_usd(usage)
    assert out["by_model"]["claude-opus-4-8"] == 30.0  # 5 + 25
    assert out["by_model"]["claude-haiku-4-5-20251001"] == 6.0  # 1 + 5
    assert out["total_usd"] == 36.0
    assert out["unpriced_models"] == []


def test_pricing_declares_unknown_model_instead_of_guessing():
    import silk_pricing as pricing

    out = pricing.estimate_cost_usd({"some-future-model": {"input_tokens": 1000,
                                                            "output_tokens": 1000}})
    assert out["total_usd"] == 0.0
    assert out["unpriced_models"] == ["some-future-model"]
    assert out["by_model"] == {}


def test_pricing_empty_usage_is_zero():
    import silk_pricing as pricing

    assert pricing.estimate_cost_usd(None) == {
        "total_usd": 0.0, "by_model": {}, "unpriced_models": [],
        "unpriced_tokens": {}, "complete": True}


def test_record_llm_usage_is_noop_outside_active_counter():
    import silk_context

    silk_context._data_counter.set(None)
    silk_context.record_llm_usage("claude-opus-4-8", 100, 200)  # no crash
    assert silk_context.data_counter() is None


def test_record_llm_usage_accumulates_per_model():
    import silk_context

    silk_context.begin_data_counter()
    silk_context.record_llm_usage("claude-opus-4-8", 100, 200)
    silk_context.record_llm_usage("claude-opus-4-8", 50, 25)
    silk_context.record_llm_usage("claude-haiku-4-5", 10, 10)
    usage = silk_context.data_counter()["llm_usage"]
    assert usage["claude-opus-4-8"] == {"input_tokens": 150, "output_tokens": 225}
    assert usage["claude-haiku-4-5"] == {"input_tokens": 10, "output_tokens": 10}


def test_anthropic_provider_complete_records_usage_via_context():
    import silk_context
    import silk_llm_provider as lp

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 42, "output_tokens": 7}}

    silk_context.begin_data_counter()
    with _env(ANTHROPIC_API_KEY="test-key"), \
         mock.patch("requests.post", return_value=_Resp()):
        lp.AnthropicProvider().complete("sys", "user", 100, "claude-opus-4-8", 5)
    usage = silk_context.data_counter()["llm_usage"]
    assert usage["claude-opus-4-8"] == {"input_tokens": 42, "output_tokens": 7}


def test_engine_economics_includes_cost_estimate():
    import silk_context
    import silk_engine

    c = silk_context.begin_data_counter()
    silk_context.record_llm_usage("claude-opus-4-8", 1_000_000, 1_000_000)
    econ = silk_engine._economics(c)
    assert econ["cost_usd_estimate"] == 30.0
    assert econ["cost_usd_by_model"] == {"claude-opus-4-8": 30.0}
    assert econ["cost_unpriced_models"] == []

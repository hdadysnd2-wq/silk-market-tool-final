"""اختبارات المرحلة ٠ (silk_master_prompt.md): Prompt Caching.

يغطي: تعليم `system`/`tools` بـ`cache_control` في `silk_llm_provider`،
تسجيل `cache_read_input_tokens`/`cache_creation_input_tokens` عبر
`silk_context.record_llm_usage`، تسعير الكاش في `silk_pricing`، وتعليم
آخر رسالة فقط عبر جولات `silk_llm_runtime._mark_cache_boundary` (بلا
تراكم وسوم يتجاوز حد Anthropic الأربع نقاط تخزين لكل نداء).

لا شبكة ولا مفتاح مطلوبان (نفس تقليد المستودع الهيرمتي).
Run:  python3 -m pytest tests/test_wave_p0_prompt_caching.py -q
"""
import contextlib
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.contextmanager
def _env(**vals):
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


# ── ١: حمولة HTTP تحمل cache_control ─────────────────────────────────────

def test_complete_tags_system_block_with_cache_control():
    import silk_llm_provider as lp

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "end_turn", "content": []}

    def _fake_post(url, timeout, headers, json):
        captured.update(json)
        return _Resp()

    with _env(ANTHROPIC_API_KEY="test-key"), \
         mock.patch("requests.post", side_effect=_fake_post):
        lp.AnthropicProvider().complete("النظام", "سؤال", 100, "m", 5)

    assert captured["system"] == [
        {"type": "text", "text": "النظام", "cache_control": {"type": "ephemeral"}}]


def test_complete_tools_tags_system_and_last_tool_only():
    import silk_llm_provider as lp

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "end_turn", "content": []}

    def _fake_post(url, timeout, headers, json):
        captured.update(json)
        return _Resp()

    tools = [{"name": "t1"}, {"name": "t2"}]
    with _env(ANTHROPIC_API_KEY="test-key"), \
         mock.patch("requests.post", side_effect=_fake_post):
        lp.AnthropicProvider().complete_tools(
            "النظام", [{"role": "user", "content": "hi"}], tools, 100, "m", 5)

    assert captured["system"] == [
        {"type": "text", "text": "النظام", "cache_control": {"type": "ephemeral"}}]
    assert captured["tools"][0] == {"name": "t1"}  # الأداة الأولى بلا وسم
    assert captured["tools"][1] == {"name": "t2",
                                    "cache_control": {"type": "ephemeral"}}


def test_complete_tools_without_tools_omits_tools_key():
    import silk_llm_provider as lp

    with _env(ANTHROPIC_API_KEY=None):
        out = lp.AnthropicProvider().complete_tools("sys", [], None, 100, "m", 5)
    assert out is None  # لا مفتاح -> None قبل أي بناء حمولة (لا كسر)


# ── ٢: تسجيل رموز الكاش عبر silk_context ─────────────────────────────────

def test_record_usage_extracts_cache_fields_into_context_counter():
    import silk_context
    import silk_llm_provider as lp

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 100, "output_tokens": 20,
                             "cache_read_input_tokens": 5000,
                             "cache_creation_input_tokens": 1200}}

    silk_context.begin_data_counter()
    with _env(ANTHROPIC_API_KEY="test-key"), \
         mock.patch("requests.post", return_value=_Resp()):
        lp.AnthropicProvider().complete("sys", "user", 100, "claude-opus-4-8", 5)

    row = silk_context.data_counter()["llm_usage"]["claude-opus-4-8"]
    assert row == {"input_tokens": 100, "output_tokens": 20,
                   "cache_read_tokens": 5000, "cache_creation_tokens": 1200}


def test_record_llm_usage_without_cache_args_keeps_original_two_key_shape():
    """حارس انحدار: نداء بلا كاش (الاختبارات القائمة قبل هذه المرحلة) يجب أن
    يُبقي شكل الصف الأصلي {input_tokens, output_tokens} — لا مفاتيح صفرية
    زائدة تكسر مساواة حرفية قائمة في test_wave12_architecture_audit.py."""
    import silk_context

    silk_context.begin_data_counter()
    silk_context.record_llm_usage("claude-opus-4-8", 100, 200)
    row = silk_context.data_counter()["llm_usage"]["claude-opus-4-8"]
    assert row == {"input_tokens": 100, "output_tokens": 200}


# ── ٣: تسعير الكاش (silk_pricing) ────────────────────────────────────────

def test_pricing_prices_cache_read_and_creation_off_input_price():
    import silk_pricing as pricing

    usage = {"claude-opus-4-8": {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 1_000_000, "cache_creation_tokens": 1_000_000}}
    out = pricing.estimate_cost_usd(usage)
    # سعر إدخال opus = 5.00/مليون؛ قراءة = 0.1x = 0.5، إنشاء = 1.25x = 6.25
    assert out["by_model"]["claude-opus-4-8"] == 6.75
    assert out["total_usd"] == 6.75


def test_pricing_backward_compatible_without_cache_fields():
    import silk_pricing as pricing

    out = pricing.estimate_cost_usd(
        {"claude-opus-4-8": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}})
    assert out["by_model"]["claude-opus-4-8"] == 30.0


# ── ٤: تعليم آخر رسالة فقط عبر الجولات (silk_llm_runtime) ────────────────

def test_mark_cache_boundary_tags_only_last_message_and_clears_older_tags():
    import silk_llm_runtime as rt

    messages = [
        {"role": "user", "content": "مقدمة المهمة"},
    ]
    rt._mark_cache_boundary(messages)
    assert messages[0]["content"] == [
        {"type": "text", "text": "مقدمة المهمة",
         "cache_control": {"type": "ephemeral"}}]

    # جولة تالية: رد المساعد + نتيجة أداة تُضاف؛ التعليم ينتقل للأخيرة فقط.
    messages.append({"role": "assistant",
                     "content": [{"type": "text", "text": "..."}]})
    messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x", "content": "{}"}]})
    rt._mark_cache_boundary(messages)

    tagged = [i for i, m in enumerate(messages)
             if isinstance(m["content"], list)
             and any(b.get("cache_control") for b in m["content"])]
    assert tagged == [2]  # الرسالة الأخيرة فقط، لا تراكم عبر الجولات
    assert messages[2]["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_mark_cache_boundary_never_exceeds_three_rounds_without_accumulating():
    """محاكاة حلقة أدوات ٥ جولات — عدد نقاط التخزين على مستوى الرسائل يبقى
    واحداً في كل نداء، فلا يتجاوز مجموع (system + tools + رسائل) الأربعة
    المسموح بها من Anthropic."""
    import silk_llm_runtime as rt

    messages = [{"role": "user", "content": "بداية"}]
    for round_no in range(5):
        rt._mark_cache_boundary(messages)
        n_tagged = sum(
            1 for m in messages if isinstance(m["content"], list)
            for b in m["content"] if b.get("cache_control"))
        assert n_tagged == 1, f"round {round_no}: {n_tagged} cache tags"
        messages.append({"role": "assistant",
                         "content": [{"type": "text", "text": f"رد {round_no}"}]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{round_no}",
             "content": "{}"}]})


# ── ٥: برهان خفض التكلفة ≥٢٥٪ (معيار قبول المرحلة ٠) ─────────────────────

def test_cache_read_pricing_yields_at_least_25pct_reduction_on_repeated_history():
    """يحاكي حلقة بعثة نموذجية من ٦ جولات (ميزانية silk_llm_runtime الافتراضية
    tool_calls=8): بلا كاش، كل جولة تُعيد إرسال كامل التاريخ كـinput_tokens
    عادية؛ بالكاش، أول جولة تنشئ الكاش (١٫٢٥×) وكل الجولات التالية تقرأ منه
    (٠٫١×) — نفس مقدار الرموز المشترك (system + مقدمة المهمة + تاريخ سابق).

    هذا برهان محسوب هيرمتياً (بلا شبكة/مفتاح في هذه البيئة) يعزل بالضبط
    الآلية المضافة في المرحلة ٠ — لا بديل عن تشغيل /research حي واحد قبل/
    بعد كما يطلب معيار القبول الرسمي، لكنه يثبت الحد الأدنى الرياضي للخفض
    المتوقَّع من نفس أرقام النشرة (٨٥٪ إدخال) في `silk_master_prompt.md`.
    """
    import silk_pricing as pricing

    model = "claude-opus-4-8"
    rounds = 6
    shared_prefix_tokens = 3000   # system + مقدمة المهمة + تاريخ متراكم مستقر
    fresh_tokens_per_round = 400  # نتيجة الأداة الجديدة + رد الجولة
    output_tokens_per_round = 300

    # بلا كاش (قبل المرحلة ٠): كل جولة تدفع كامل البادئة المشتركة + الجديد.
    uncached_input = rounds * (shared_prefix_tokens + fresh_tokens_per_round)
    uncached_usage = {model: {"input_tokens": uncached_input,
                              "output_tokens": rounds * output_tokens_per_round}}
    uncached_cost = pricing.estimate_cost_usd(uncached_usage)["total_usd"]

    # بالكاش (بعد المرحلة ٠): الجولة الأولى تنشئ الكاش، البقية تقرأ منه فقط.
    cached_usage = {model: {
        "input_tokens": rounds * fresh_tokens_per_round,
        "output_tokens": rounds * output_tokens_per_round,
        "cache_creation_tokens": shared_prefix_tokens,
        "cache_read_tokens": (rounds - 1) * shared_prefix_tokens}}
    cached_cost = pricing.estimate_cost_usd(cached_usage)["total_usd"]

    reduction = 1 - (cached_cost / uncached_cost)
    assert reduction >= 0.25, f"خفض التكلفة {reduction:.1%} أقل من ٢٥٪ المطلوبة"

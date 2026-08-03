"""أسعار نماذج كلود — Claude model pricing constants (تدقيق المعمارية، دين ٤).

المصدر الوحيد لتسعير التشغيلات — دولار لكل مليون رمز (توثيق Anthropic
الرسمي وقت الكتابة، `SILK_AI_MODEL`/`SILK_AI_FAST_MODEL` في silk_ai_judge.py).
نموذج غير مُدرَج هنا يُستبعد من التقدير ويُعلَن في `unpriced_models` — لا
تخمين سعر لنموذج مجهول (نفس مبدأ لا اختلاق المطبَّق على البيانات).
"""
from __future__ import annotations

# دولار لكل مليون رمز {"input": ..., "output": ...} — USD per 1M tokens.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}

# بادئات لمطابقة معرّفات مؤرَّخة (مثال: claude-haiku-4-5-20251001) بأسرة
# التسعير الصحيحة — أطول بادئة أولاً كي "claude-opus-4-8" لا يطابق أسرة أحدث لاحقاً.
_PRICING_PREFIXES: tuple[str, ...] = tuple(
    sorted(MODEL_PRICING, key=len, reverse=True))


def _pricing_for(model: str) -> dict[str, float] | None:
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for prefix in _PRICING_PREFIXES:
        if model.startswith(prefix):
            return MODEL_PRICING[prefix]
    return None


# مضاعفات تسعير الكاش على سعر الإدخال (توثيق Anthropic الرسمي، Prompt
# Caching): قراءة من الكاش أرخص، كتابة/إنشاء إدخالة كاش أغلى من الإدخال العادي.
_CACHE_READ_MULT = 0.1
_CACHE_CREATION_MULT = 1.25


def estimate_cost_usd(llm_usage: dict | None) -> dict:
    """قدّر تكلفة التشغيلة بالدولار من عدّاد الاستهلاك لكل نموذج.

    المدخل بشكل `silk_context.record_llm_usage` المتراكم:
    {model: {"input_tokens": N, "output_tokens": N, "cache_read_tokens": N,
    "cache_creation_tokens": N}} — حقلا الكاش اختياريان (نداءات بلا كاش تبقى
    صحيحة بلا تعديل).
    المخرَج: {"total_usd", "by_model", "unpriced_models", "unpriced_tokens",
    "complete"} — نموذج بلا سعر معروف يُستبعد من المجموع ويُسمّى صراحة في
    unpriced_models، لا يُصفَّر بصمت.

    **إغلاق نقطة عمياء في القياس**: إسقاط نموذج مجهول من المجموع كان يجعل
    `total_usd` يُبلِّغ أقل من الواقع بصمت (نداءات حقيقية استُهلكت، لكن قارئ
    total_usd وحده لا يراها). لا نخمّن سعراً لنموذج مجهول (لا اختلاق)، لكن
    الرموز مرصودة لا مُخمَّنة — فنُظهِر إجمالي رموز كل نموذج غير مُسعَّر في
    `unpriced_tokens`، ونضع `complete=False` كي يعرف المستهلك أن المجموع
    ناقص. القيمة الدولارية تبقى صادقة (النماذج المُسعَّرة فقط).
    """
    total = 0.0
    by_model: dict[str, float] = {}
    unpriced: list[str] = []
    unpriced_tokens: dict[str, dict[str, int]] = {}
    for model, tok in (llm_usage or {}).items():
        pricing = _pricing_for(model)
        if pricing is None:
            unpriced.append(model)
            # رموز مرصودة لا مُسعَّرة — تُعرَض كما هي، لا تُصفَّر ولا تُخمَّن.
            unpriced_tokens[model] = {
                "input_tokens": int(tok.get("input_tokens", 0) or 0),
                "output_tokens": int(tok.get("output_tokens", 0) or 0)}
            continue
        cost = ((tok.get("input_tokens", 0) or 0) / 1_000_000 * pricing["input"]
                + (tok.get("output_tokens", 0) or 0) / 1_000_000 * pricing["output"]
                + (tok.get("cache_read_tokens", 0) or 0) / 1_000_000
                  * pricing["input"] * _CACHE_READ_MULT
                + (tok.get("cache_creation_tokens", 0) or 0) / 1_000_000
                  * pricing["input"] * _CACHE_CREATION_MULT)
        by_model[model] = round(cost, 6)
        total += cost
    return {"total_usd": round(total, 6), "by_model": by_model,
           "unpriced_models": sorted(unpriced),
           "unpriced_tokens": unpriced_tokens,
           "complete": not unpriced}


if __name__ == "__main__":
    print(estimate_cost_usd({
        "claude-opus-4-8": {"input_tokens": 100_000, "output_tokens": 20_000},
        "claude-haiku-4-5-20251001": {"input_tokens": 50_000, "output_tokens": 5_000},
    }))

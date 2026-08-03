"""بلاغ حي إنتاجي — أول تشغيلة حيّة بعد الأمر #6 (عسل طبيعي/المملكة المتحدة):

قضيتان P0 اكتُشفتا معاً، والدرس ١٦ في docs/LESSONS.md يعمّمهما:

القضية ١ — انهيار سردي كامل («بلغ التوليد الحدّ الأقصى للطول»): ميزانية رموز
  الكاتب (الأمر #6/E2) ضُبطت تحت ما تتطلّبه محتويات أربعة أوامر سابقة مجتمعةً
  لأول مرّة — B1 (مسرد + شروح + ريال)، C5 (جدول مستوردين)، D2 (خمس تقاطعات)،
  D3 (WGI). المسوّدة تُقتطع، ونداء الإكمال كان يأخذ الميزانية الأساسية (٨٠٠٠)
  لا السقف، فلا يُنهي ذيلاً كبيراً => report=None => هيكل احتياطي بلا سرد.
  الإصلاح: أول محاولة تتّسع لتقرير كامل في نداء واحد، والسقف يوسَّع، ونداء
  الإكمال يأخذ **السقف** لا الأساس.

القضية ٢ — التكلفة المعروضة لا تطابق المفوتَرة (⚠ «يستثني نماذج غير مُسعَّرة»):
  كل نموذج يُوجَّه إليه الكود افتراضياً يجب أن يكون في دفتر أسعار silk_pricing
  (وإلّا يُستبعَد من المجموع بصمت)، ونداءات الاقتطاع/الفشل التي تحرق رموزاً
  قبل فشلها يجب أن تبقى محتسَبة، وطريقة المصالحة موثَّقة ومقفولة باختبار.

هيرمتي بالكامل — لا شبكة، لا مفتاح حقيقي. Run:
  python3 -m pytest tests/test_command6_regression_budget_and_pricing.py -q
"""
from __future__ import annotations

import contextlib
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from silk_pricing import estimate_cost_usd


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


def _resp(payload: dict):
    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return payload
    return _R()


@pytest.fixture(autouse=True)
def _reset_provider_context():
    """نظافة الحالة: هذه الاختبارات تنادي المزوّد الحقيقي (requests.post) فتضبط
    `_last_stop_reason`/`_last_error` (contextvar). في الإنتاج يعيد المزوّد
    ضبطهما مع كل نداء، لكن اختباراً لاحقاً يُرقِّع `_call` (لا المزوّد) قد يقرأ
    قيمة متسرّبة — فنُصفّرهما بعد كل اختبار كي لا يلوّث هذا الملف غيره."""
    yield
    import silk_llm_provider as _lp
    _lp._last_stop_reason.set(None)
    _lp._last_error.set(None)


def _mission_reports():
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    return {"trade_flow": AgentReport(
        "LLMAgent:trade_flow",
        [DataPoint("واردات المملكة المتحدة 120 مليون دولار", "UN Comtrade",
                   0.9, "note")],
        False, "ok")}


# تقرير كامل من الأحد عشر قسماً بالترتيب الإلزامي — يمرّ فحص الاكتمال
# (_writer_incomplete == []). فقرات موجزة تكفي للبنية (المحتوى ليس المقصود هنا).
def _full_11_section_report() -> str:
    import silk_ai_judge as aj
    parts = []
    for i, title in enumerate(aj._REPORT_SECTIONS, start=1):
        parts.append(f"## {i}. {title}\nفقرة القسم تنتهي بجملة سليمة كاملة.")
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# القضية ١ — ميزانية رموز الكاتب تتّسع لمجموع محتوى الأوامر السابقة
# ═══════════════════════════════════════════════════════════════════════════

def test_writer_first_attempt_budget_exceeds_measured_full_narrative():
    """قِسْ متطلَّب سرد كامل من أوفى عيّنة مشحونة، واطلب أن تتجاوزه ميزانية
    المحاولة الأولى مع هامش يغطّي الكتل الأربع التي لم تجتمع في العيّنة بعد
    (B1 المسرد الكامل + D2 الخمس تقاطعات + C5 الجدول + D3). القيمة القديمة
    (٨٠٠٠) كانت تحت هذا المتطلَّب — الانحدار الحيّ بالضبط."""
    import silk_ai_judge as aj

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fullest = 0
    for name in ("samples/report_full_latest.md",
                 "samples/research_report_latest.md"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            fullest = max(fullest, len(open(p, encoding="utf-8").read()))
    assert fullest > 0, "عيّنة مرجعية مفقودة — لا يمكن قياس المتطلَّب"

    # تقدير رموز الإخراج للعربية: ~٢.٥ حرف/رمز (تقدير متحفّظ). العيّنة الأوفى
    # لا تحمل الكتل الأربع مجتمعةً بعد، فنضربها في عامل الكتل (×٢) — تقرير
    # كامل بكل الكتل يقارب ضعف الأوفى الحالي.
    sample_tokens = fullest / 2.5
    combined_requirement = sample_tokens * 2.0
    assert aj._WRITER_MAX_TOKENS >= combined_requirement, (
        f"ميزانية المحاولة الأولى ({aj._WRITER_MAX_TOKENS}) دون المتطلَّب "
        f"المقيس للسرد الكامل بكل الكتل (~{combined_requirement:.0f})")
    # والسقف الصلب يترك هامش تصعيد فوق الأساس (لا يساويه فيُلغي التصعيد).
    assert aj._MAX_TOKENS_CEILING >= 2 * aj._WRITER_MAX_TOKENS


def test_writer_continuation_call_uses_the_ceiling_not_the_base_budget():
    """نداء الإكمال يجب أن يأخذ **السقف الصلب** لا الميزانية الأساسية: ذيل
    كبير (جدول C5 + تقاطعات D2 + حدود) لا يُنهيه ٨٠٠٠ رمزاً فيُهدَر التقرير
    كله (report=None => هيكل). كان يستعمل _WRITER_MAX_TOKENS."""
    import silk_ai_judge as aj
    import silk_llm_provider as lp
    seen: list[tuple[bool, int]] = []

    def fake_post(url, **kw):
        body = kw["json"]
        user = body["messages"][0]["content"]
        is_cont = "مهمة إكمال" in user
        seen.append((is_cont, body["max_tokens"]))
        if is_cont:                      # نداء الإكمال ينجح
            return _resp({"stop_reason": "end_turn",
                          "content": [{"type": "text",
                                       "text": _full_11_section_report()}],
                          "usage": {"input_tokens": 50, "output_tokens": 200}})
        # المسوّدة تُقتطع دائماً حتى يُفرَض نداء إكمال
        return _resp({"stop_reason": "max_tokens",
                      "content": [{"type": "text", "text": "## 1. الخلاصة\nمقتطع"}],
                      "usage": {"input_tokens": 50, "output_tokens": 100}})

    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY="x"), \
         mock.patch("requests.post", side_effect=fake_post):
        aj.deep_report(_mission_reports(), "محلل", {"verdict": "WATCH"},
                       "عسل طبيعي", "المملكة المتحدة")
    cont_caps = [cap for is_cont, cap in seen if is_cont]
    assert cont_caps, "لم يُستدعَ نداء الإكمال — البنية تغيّرت"
    assert cont_caps[0] == aj._MAX_TOKENS_CEILING, (
        f"نداء الإكمال أخذ {cont_caps[0]} لا السقف {aj._MAX_TOKENS_CEILING}")
    assert cont_caps[0] > aj._WRITER_MAX_TOKENS   # أوسع من الأساس صراحةً


def test_full_report_with_all_blocks_completes_end_to_end_not_skeleton():
    """المسار الحيّ بالضبط: سرد كامل يحمل B1+C5+D2+D3 مجتمعةً يتطلّب رموزاً
    تفوق السقف القديم (١٦٠٠٠). بالميزانية القديمة يُقتطع فيفشل (report=None =>
    هيكل)؛ بالموسّعة ينجح نداءٌ واحد ويعود تقرير مكتمل (لا هيكل)."""
    import silk_ai_judge as aj
    import silk_llm_provider as lp
    # يمثّل متطلَّب السرد الكامل بكل الكتل — أعلى من السقف القديم (١٦٠٠٠).
    required = 18_000
    full = _full_11_section_report()

    def fake_post(url, **kw):
        cap = kw["json"]["max_tokens"]
        if cap >= required:              # ميزانية كافية => التقرير كاملاً
            return _resp({"stop_reason": "end_turn",
                          "content": [{"type": "text", "text": full}],
                          "usage": {"input_tokens": 100, "output_tokens": 900}})
        # ميزانية قاصرة => اقتطاع (نص جزئي + max_tokens)
        return _resp({"stop_reason": "max_tokens",
                      "content": [{"type": "text",
                                   "text": "## 1. " + aj._REPORT_SECTIONS[0]
                                           + "\nمقتطع دون اكتمال وي"}],
                      "usage": {"input_tokens": 100, "output_tokens": 300}})

    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY="x"), \
         mock.patch("requests.post", side_effect=fake_post):
        out = aj.deep_report(_mission_reports(), "محلل", {"verdict": "WATCH"},
                             "عسل طبيعي", "المملكة المتحدة")
    assert out is not None, "فشل توليد السرد الكامل — عاد هيكل احتياطي"
    assert aj._writer_incomplete(out) == [], (
        f"التقرير غير مكتمل رغم النجاح: {aj._writer_incomplete(out)}")


def test_analyst_budget_exceeds_the_single_mission_default():
    """المحلل ينتج D2 (خمس تقاطعات + SWOT بتثليث ومقارنات) — إخراج ثقيل. كان
    يأخذ نفس ميزانية بعثة أداة واحدة (6000 رمزاً) عبر `budget=None`؛ فإن اقتُطع
    JSON فشلت التقاطعات الخمس إلى «دليل غير كافٍ». يجب أن يُمرَّر المحلل ميزانية
    إخراج أكبر من الافتراضي حين لا يُمرَّر أحد صراحةً."""
    import silk_market_analyst as ma
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    captured: dict = {}

    def fake_run_llm_agent(mission, market, **kw):
        captured["budget"] = kw.get("budget")
        return AgentReport("LLMAgent:market_analyst",
                           [DataPoint("x", "s", 0.5, "[demand] n")], False, "ok")

    ref = ma.MarketRef(iso3="GBR", m49="826", name_en="United Kingdom",
                       name_ar="المملكة المتحدة")
    with mock.patch.object(ma, "run_llm_agent", side_effect=fake_run_llm_agent):
        ma.analyze_market(ref, "عسل طبيعي", {})   # budget=None => يُملأ افتراضاً أكبر
    budget = captured["budget"] or {}
    got = budget.get("max_output_tokens", 0)
    from silk_llm_runtime import _DEFAULT_BUDGET
    assert got > _DEFAULT_BUDGET["max_output_tokens"], (
        f"ميزانية المحلل ({got}) ليست أكبر من افتراضي البعثة الواحدة "
        f"({_DEFAULT_BUDGET['max_output_tokens']})")
    assert got >= 12_000     # تتّسع للتقاطعات الخمس + SWOT بلا اقتطاع


# ═══════════════════════════════════════════════════════════════════════════
# القضية ٢ — مصالحة التكلفة: كل نموذج مُوجَّه مُسعَّر، ونداءات الاقتطاع محتسَبة
# ═══════════════════════════════════════════════════════════════════════════

def test_every_default_routed_model_is_priced():
    """الدرس ١٦ (النصف الثاني): تكامل نموذج جديد يُضاف لدفتر الأسعار في نفس
    الأمر الذي يُدخِله. حارس ميكانيكي: كل نموذج يُوجَّه إليه الكود افتراضياً
    (ذكي/سريع/بعثات) موجود في silk_pricing — وإلّا يُستبعَد من المجموع فتظهر
    ⚠ وتكلفةٌ أدنى من الواقع. لو أدخل E2 نموذجاً غير مُسعَّر لأحمرّ هذا فوراً."""
    import silk_ai_judge as aj
    import silk_llm_runtime as rt
    import silk_market_analyst as ma
    from silk_pricing import _pricing_for

    routed = {
        "ذكي/محلل/كاتب/توليف (silk_ai_judge._MODEL)": aj._MODEL,
        "سريع/مراجع/إضافات (silk_ai_judge._FAST_MODEL)": aj._FAST_MODEL,
        "بعثات (silk_llm_runtime._MISSION_MODEL)": rt._MISSION_MODEL,
        "محلل-ذكي (silk_market_analyst._SMART_MODEL)": ma._SMART_MODEL,
    }
    unpriced = {role: m for role, m in routed.items() if _pricing_for(m) is None}
    assert not unpriced, f"نماذج مُوجَّهة بلا سعر في الدفتر: {unpriced}"


def test_maxtokens_truncated_call_still_meters_its_burned_tokens():
    """القضية ٢، الخطوة ٢: نداء يعود None بسبب اقتطاع max_tokens (رد HTTP 200
    بلا نص) حرَق رموزاً فعلاً قبل فشله — يجب أن تبقى محتسَبة في العدّاد
    والتكلفة، لا تُسقَط من التبليغ (وإلّا التكلفة المعروضة < المفوتَرة)."""
    import silk_llm_provider as lp
    import silk_context

    def fake_post(url, **kw):
        return _resp({"stop_reason": "max_tokens", "content": [],
                      "usage": {"input_tokens": 1200, "output_tokens": 800}})

    c = silk_context.begin_data_counter()
    try:
        with _env(ANTHROPIC_API_KEY="k"), \
             mock.patch("requests.post", side_effect=fake_post):
            out = lp.AnthropicProvider().complete(
                "s", "u", 8000, "claude-opus-4-8", 5)
    finally:
        pass
    assert out is None                                    # اقتطاع بلا نص => فجوة
    row = c["llm_usage"]["claude-opus-4-8"]
    assert row["input_tokens"] == 1200 and row["output_tokens"] == 800
    assert estimate_cost_usd(c["llm_usage"])["total_usd"] > 0   # ومُسعَّرة


def test_displayed_cost_reconciles_with_recorded_usage_within_tolerance():
    """طريقة المصالحة الموثَّقة: التكلفة المعروضة = Σ لكل نموذج
    (رموز_إدخال×سعر_إدخال + رموز_إخراج×سعر_إخراج + حدود الكاش). نعيد الحساب
    يدوياً من نفس الأرقام المرصودة ونطابق ضمن تفاوت ضئيل. لقطة تشغيلة كاملة
    واقعية (بعثات Haiku + محلل/كاتب Opus بما فيه تصعيد) — التكلفة الصادقة
    تقارب ما يفوتره Anthropic، لا $0.39. أي نموذج بلا سعر يُعلَن لا يختفي."""
    usage = {
        "claude-haiku-4-5-20251001": {"input_tokens": 600_000,
                                      "output_tokens": 40_000},
        "claude-opus-4-8": {"input_tokens": 180_000, "output_tokens": 90_000},
    }
    out = estimate_cost_usd(usage)
    manual = (600_000 / 1e6 * 1.00 + 40_000 / 1e6 * 5.00
              + 180_000 / 1e6 * 5.00 + 90_000 / 1e6 * 25.00)
    assert out["total_usd"] == pytest.approx(manual, rel=1e-9)
    assert out["complete"] is True and out["unpriced_models"] == []
    # التكلفة الصادقة لتشغيلة كهذه ضِعف دولارات لا سنتات (يفسّر ~$3 لا $0.39).
    assert out["total_usd"] > 2.0
    # نموذج بيئي غير مُسعَّر (تجاوز env) يُعلَن صراحةً، لا يُصفَّر بصمت.
    out2 = estimate_cost_usd(
        {**usage, "env-override-model": {"input_tokens": 10_000,
                                         "output_tokens": 5_000}})
    assert out2["complete"] is False
    assert "env-override-model" in out2["unpriced_models"]
    assert out2["unpriced_tokens"]["env-override-model"]["output_tokens"] == 5_000

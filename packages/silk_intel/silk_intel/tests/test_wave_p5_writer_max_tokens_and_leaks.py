"""بلاغ حي إنتاجي (تمور/هولندا HS080410) — إصلاح ثلاث قضايا بدليل مُلتقَط:

القضية ١ — فشل الكاتب بـstop_reason="max_tokens" (سلسلة PRs #69/#70/#71):
  رد HTTP 200 بلا كتل نصية كان يعيد None فيصير report=None. الآن يصعّد
  مزوّد كلود سقف الإخراج ويعيد المحاولة، ويعيد أوفى نص — max_tokens لا
  يسبّب report=None بعد اليوم (silk_llm_provider.complete).

القضية ٢ — تسريب JSON خام للواجهة: أشكال (سياج ```json، JSON مضمَّن،
  لاحقة "| tool calls: N") فاتت المُطهِّر المُرسَّى القديم. الآن تُطهَّر
  (silk_render._strip_raw_json_leak) وحارس الجودة يلتقط مفاتيح JSON العربية.

القضية ٣ — تصدير docx حين report=None: يُصدَّر مستند بالحكم + الأدلة +
  الفجوات + ملاحظة متدهورة صريحة بدل فشل صامت (silk_reports.render_client_docx).

هيرمتي بالكامل — لا شبكة، لا مفتاح حقيقي. Run:
  python3 -m pytest tests/test_wave_p5_writer_max_tokens_and_leaks.py -q
"""
from __future__ import annotations

import contextlib
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


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


# ═══ القضية ١ — استرداد الكاتب من نفاد رموز الإخراج (تصعيد مُتتبَّع) ═══════

def _mission_reports():
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    return {"trade_flow": AgentReport(
        "LLMAgent:trade_flow",
        [DataPoint("واردات هولندا 33 مليون دولار", "UN Comtrade", 0.9, "note")],
        False, "ok")}


# ── المزوّد: نداء مفرد يعرض stop_reason (لا حلقة مخفية داخله) ──────────────

def test_complete_is_single_shot_and_records_stop_reason():
    """المزوّد طبقة HTTP رقيقة: نداء واحد لكل استدعاء، ويعرض stop_reason
    لطبقة الكاتب (لا تصعيد داخلي)."""
    import silk_llm_provider as lp
    n = {"c": 0}

    def fake_post(url, **kw):
        n["c"] += 1
        return _resp({"stop_reason": "end_turn",
                      "content": [{"type": "text", "text": "رد."}],
                      "usage": {"input_tokens": 5, "output_tokens": 5}})

    with _env(ANTHROPIC_API_KEY="k"), \
         mock.patch("requests.post", side_effect=fake_post):
        out = lp.AnthropicProvider().complete("s", "u", 900, "m", 5)
    assert out == "رد." and n["c"] == 1              # نداء واحد فقط
    assert lp.last_stop_reason() == "end_turn"


def test_complete_returns_truncated_text_on_max_tokens_with_text():
    """اقتطاع مع نص → يُعاد النص الجزئي (لا None)، وstop_reason='max_tokens'
    معروض كي تقرّر طبقة الكاتب التصعيد."""
    import silk_llm_provider as lp

    def fake_post(url, **kw):
        return _resp({"stop_reason": "max_tokens",
                      "content": [{"type": "text", "text": "جزء من التقرير"}],
                      "usage": {"input_tokens": 10, "output_tokens": 30}})

    with _env(ANTHROPIC_API_KEY="k"), \
         mock.patch("requests.post", side_effect=fake_post):
        out = lp.AnthropicProvider().complete("s", "u", 8000, "m", 5)
    assert out == "جزء من التقرير" and lp.last_error() is None
    assert lp.last_stop_reason() == "max_tokens"


def test_complete_max_tokens_no_text_declares_gap_and_signals_stop_reason():
    """اقتطاع بلا نص → None + empty_response معلَن، وstop_reason='max_tokens'
    معروض (فيعرف الكاتب أنه اقتطاع لا فشل شبكة). لا اختلاق."""
    import silk_llm_provider as lp

    def fake_post(url, **kw):
        return _resp({"stop_reason": "max_tokens", "content": [],
                      "usage": {"input_tokens": 10, "output_tokens": 5}})

    with _env(ANTHROPIC_API_KEY="k"), \
         mock.patch("requests.post", side_effect=fake_post):
        out = lp.AnthropicProvider().complete("s", "u", 8000, "m", 5)
    assert out is None
    err = lp.last_error()
    assert err and err["type"] == "empty_response" and "max_tokens" in err["message"]
    assert lp.last_stop_reason() == "max_tokens"


# ── الكاتب: التصعيد عند طبقة الكاتب، كل محاولة نداءٌ مُتتبَّع مستقل ─────────

def test_writer_recovers_end_to_end_from_max_tokens_no_text():
    """المسار الإنتاجي بالضبط: أول محاولة للكاتب max_tokens-بلا-نص (كانت
    تعطي report=None)، فيصعّد الكاتب السقف والمحاولة الثانية تنجح — يُعاد نص."""
    import silk_ai_judge as aj
    posts = {"n": 0}

    def fake_post(url, **kw):
        posts["n"] += 1
        if posts["n"] == 1:
            return _resp({"stop_reason": "max_tokens", "content": [],
                          "usage": {"input_tokens": 20, "output_tokens": 20}})
        return _resp({"stop_reason": "end_turn",
                      "content": [{"type": "text",
                                   "text": "## 1. الخلاصة\nتقرير مسترَدّ."}],
                      "usage": {"input_tokens": 20, "output_tokens": 60}})

    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY="x"), \
         mock.patch("requests.post", side_effect=fake_post):
        out = aj.deep_report(_mission_reports(), "مسوّدة المحلل",
                             {"verdict": "WATCH"}, "تمور", "هولندا")
    assert out and "تقرير مسترَدّ" in out       # لا None بسبب max_tokens
    assert posts["n"] == 2                       # صُعِّد مرة واحدة (نجح بعدها)


def test_writer_escalation_is_bounded_and_traces_each_attempt():
    """اقتطاع دائم بلا نص → التصعيد مُقيَّد بـ_MAX_TOKENS_RETRIES+1 محاولة،
    و**كل محاولة تُصدر report_call event مستقلاً** بمرحلة متصاعدة، والسقف
    يتضاعف؛ النتيجة النهائية فجوة معلنة (None) لا اختلاق."""
    import silk_ai_judge as aj
    import silk_trace
    caps: list[int] = []

    def fake_post(url, **kw):
        caps.append(kw["json"]["max_tokens"])
        return _resp({"stop_reason": "max_tokens", "content": [],
                      "usage": {"input_tokens": 10, "output_tokens": 5}})

    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY="x"), \
         mock.patch("requests.post", side_effect=fake_post):
        out = aj.deep_report(_mission_reports(), "محلل",
                             {"verdict": "WATCH"}, "تمور", "هولندا",
                             trace_id="run-p5-bounded")
    assert out is None                           # فجوة معلنة، لا اختلاق
    # مقيَّد بـسقفين: _MAX_TOKENS_RETRIES (≤4 محاولات) والسقف الصلب. بالقيم
    # الافتراضية (16000→32000، رُفعت لبلاغ عسل/المملكة المتحدة) يبلغ التضعيفُ
    # السقفَ الصلب بخطوة واحدة، فيتوقّف عند محاولتين (إعادة النداء بنفس السقف
    # لا تفيد) — كلاهما حدّ صريح.
    assert aj._MAX_TOKENS_RETRIES == 3            # الحدّ الأقصى المعلن للمحاولات
    assert caps == [16000, 32000]                 # صعّد مرة للسقف الصلب ثم توقّف
    events = [e for e in silk_trace.read_trace("run-p5-bounded")
              if e.get("kind") == "report_call"]
    assert len(events) == 2                       # حدث report_call مستقل لكل محاولة
    assert [e["stage"] for e in events] == ["draft", "draft_escalate1"]


def test_writer_escalation_meters_every_attempt_in_cost():
    """كل محاولة تصعيد تُحسَب وتُقاس: llm_calls يزيد لكل محاولة، ورموزها
    تتراكم في تقدير التكلفة (الذيل خارج سقف النداءات الكلي فالقياس شرط)."""
    import silk_ai_judge as aj
    import silk_context
    from silk_pricing import estimate_cost_usd

    def fake_post(url, **kw):  # اقتطاع دائم *مع* نص جزئي → out ليس None
        return _resp({"stop_reason": "max_tokens",
                      "content": [{"type": "text", "text": "جزء"}],
                      "usage": {"input_tokens": 100, "output_tokens": 50}})

    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY="x"), \
         mock.patch("requests.post", side_effect=fake_post):
        c = silk_context.begin_data_counter()
        out = aj.deep_report(_mission_reports(), "محلل",
                             {"verdict": "WATCH"}, "تمور", "هولندا")
    # §5 (أمر العمل الرئيس): اقتطاع دائم حتى بعد نداء الإكمال الواحد =>
    # إخفاق داخلي صريح (None)، لا تقرير جزئي يُشحن. القياس يبقى شرطاً: كلّ
    # محاولة تصعيد + نداء الإكمال عُدّت ورموزها تراكمت في التكلفة.
    assert out is None
    assert c["llm_calls"] == 3                     # محاولتا التصعيد + نداء الإكمال
    usage = c["llm_usage"]
    total_out = sum(v.get("output_tokens", 0) for v in usage.values())
    assert total_out >= 150                        # 3×50 إخراج متراكم
    assert estimate_cost_usd(usage)["total_usd"] > 0


def test_normal_writer_makes_exactly_one_attempt_no_escalation():
    """رد طبيعي (end_turn) → محاولة واحدة، حدث report_call واحد، بلا تصعيد —
    مسار النجاح العادي غير متأثّر."""
    import silk_ai_judge as aj
    import silk_trace
    n = {"c": 0}

    def fake_post(url, **kw):
        n["c"] += 1
        return _resp({"stop_reason": "end_turn",
                      "content": [{"type": "text", "text": "## 1. تقرير كامل."}],
                      "usage": {"input_tokens": 10, "output_tokens": 40}})

    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY="x"), \
         mock.patch("requests.post", side_effect=fake_post):
        out = aj.deep_report(_mission_reports(), "محلل", {"verdict": "WATCH"},
                             "تمور", "هولندا", trace_id="run-p5-normal")
    assert out and n["c"] == 1                     # نداء واحد فقط
    events = [e for e in silk_trace.read_trace("run-p5-normal")
              if e.get("kind") == "report_call"]
    assert len(events) == 1 and events[0]["stage"] == "draft"


# ═══ القضية ٢ — تسريب JSON خام للواجهة (سلاسل إنتاجية حرفية) ══════════════

# السلاسل بالضبط كما ظهرت في الإنتاج (بلاغ المالك، القضية ٢).
_LEAK_VERDICT_EMBEDDED = (
    'التوصية: {"verdict":"مراقبة السوق","confidence":0.55,'
    '"reasoning":"مبني على الحقائق والخيوط."}')
_LEAK_VERDICT_ARABIC_KEYS = (
    '{"الحكم":"مراقبة السوق","درجة الثقة":0.55,'
    '"reasoning":"مبني على الحقائق."}')
_LEAK_FENCED_FINDINGS = (
    'json { "findings": [ { "claim": "ادّعاء", '
    '"datapoint_ids": ["",""] } ] } | tool calls: 2')
_LEAK_UNPARSEABLE_SUFFIX = "رد كلود غير قابل للتفسير كـ JSON | tool calls: 2"


def _assert_no_raw_plumbing(out: str):
    assert "{" not in out and "}" not in out, out
    assert '"findings"' not in out and '"datapoint_ids"' not in out, out
    assert '"verdict"' not in out and '"confidence"' not in out, out
    assert '"الحكم"' not in out and '"درجة الثقة"' not in out, out
    assert "tool calls" not in out and "نداءات أدوات" not in out, out


def test_embedded_verdict_json_is_neutralized_to_reasoning():
    from silk_render import _strip_internal_plumbing
    out = _strip_internal_plumbing(_LEAK_VERDICT_EMBEDDED)
    _assert_no_raw_plumbing(out)
    assert "مبني على الحقائق والخيوط" in out   # استُخرج التعليل المقروء


def test_arabic_keyed_verdict_json_is_neutralized():
    from silk_render import _strip_internal_plumbing
    out = _strip_internal_plumbing(_LEAK_VERDICT_ARABIC_KEYS)
    _assert_no_raw_plumbing(out)
    assert "مبني على الحقائق" in out


def test_fenced_findings_json_with_tool_calls_suffix_becomes_declared_gap():
    from silk_render import _strip_internal_plumbing
    out = _strip_internal_plumbing(_LEAK_FENCED_FINDINGS)
    _assert_no_raw_plumbing(out)
    assert "json" not in out.lower()
    # §2 (أمر العمل الرئيس): جملة الفجوة لا تذكر «كلود» — صياغة محايدة.
    assert "تعذّرت قراءة" in out                # فجوة معلنة بدل JSON خام
    assert "كلود" not in out


def test_unparseable_gap_line_keeps_message_but_drops_tool_calls_suffix():
    from silk_render import _strip_internal_plumbing
    out = _strip_internal_plumbing(_LEAK_UNPARSEABLE_SUFFIX)
    assert "tool calls" not in out and "|" not in out
    # §2: بلا ذكر «كلود» — الفجوة تُصاغ محايدةً موجَّهةً للقارئ.
    assert "تعذّرت قراءة بيانات هذا البند" in out
    assert "كلود" not in out


def test_quality_gate_flags_arabic_keyed_raw_json():
    """حارس الانحدار: مفتاح JSON عربي مسرَّب كان يفلت من [a-zA-Z_]+ —
    الآن يلتقطه _RAW_JSON_RE الموسَّع."""
    from silk_quality_gate import _check_markdown_and_raw_json
    findings = _check_markdown_and_raw_json(_LEAK_VERDICT_ARABIC_KEYS)
    assert any(f["check"] == "raw_json" for f in findings)


# ═══ القضية ٣ — تصدير docx متدهور حين report=None ════════════════════════

def _research_view_report_none():
    import silk_render
    result = {
        "product": "تمور", "hs_code": "080410",
        "market": {"name_ar": "هولندا", "name_en": "Netherlands", "iso3": "NLD"},
        "header": {"product": "تمور", "hs_code": "080410",
                   "target_market": "هولندا", "date": "2026-07-15"},
        "deep_research": {
            "verdict": {"verdict": "WATCH", "confidence": 0.55,
                        "ai": {"verdict": "WATCH", "reasoning": "مبني على الحقائق."}},
            "report": {"report": None, "unresolved_notes": [],
                       "failure_reason": "فشل نداء كلود (empty_response: "
                                         "HTTP 200 بلا كتل نصية — "
                                         "stop_reason='max_tokens')"},
            "analyst": {"summary": "x", "missing_categories": ["price_competitiveness"],
                        "by_category": {}},
            "missions": {}, "limits": [], "trace_id": "t"},
    }
    return silk_render.build_view(result)


def test_client_docx_with_report_none_exports_degraded_not_failure():
    pytest.importorskip("docx")
    import tempfile
    import silk_reports
    from conftest import docx_all_text
    with _env(SILK_HERMETIC="1"):
        view = _research_view_report_none()
        path = silk_reports.render_client_docx(
            view, os.path.join(tempfile.mkdtemp(), "r.docx"))
    txt = docx_all_text(path)
    assert "مراقبة السوق" in txt                # الحكم حاضر
    assert "لأسباب تقنية مؤقتة" in txt          # ملاحظة التدهور الصريحة
    assert "إعادة توليد" in txt                 # طريق الخروج معلن
    # لا يتسرّب تفصيل تشغيلي خام للعميل (حارس _client_assert_clean لم يُكسَر).
    assert "max_tokens" not in txt and "stop_reason" not in txt


def test_operator_docx_with_report_none_surfaces_failure_reason():
    pytest.importorskip("docx")
    import tempfile
    import silk_reports
    from conftest import docx_all_text
    with _env(SILK_HERMETIC="1"):
        view = _research_view_report_none()
        path = silk_reports.render_docx(
            view, os.path.join(tempfile.mkdtemp(), "op.docx"))
    txt = docx_all_text(path)
    # التصدير التشغيلي (للمدقّق) يُظهر سبب الفشل عبر «حدود هذا التقرير».
    assert "التقرير الكامل غائب" in txt

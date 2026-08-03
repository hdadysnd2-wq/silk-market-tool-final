"""اختبارات بلاغ حي ثالث (تمور/هولندا): كاتب التقرير فشل للمرة الثالثة
"مهلة أو خطأ شبكة" بلا أي دليل على نوع الفشل الفعلي — والتقاطعات الخمسة
باتت بلغة تجارية لكن بعثة risk_news كشفت عطلاً جديداً: JSON خام يُعرض
كنص. المطلوب: توقّف عن التخمين (التقط نوع الاستثناء الفعلي)، وأصلح
تسريب JSON الخام بدل التعامل مع الأعراض فقط.

يغطي:
1. silk_llm_provider: فصل مهلتَي الاتصال/القراءة (يُفشل مشاكل الاتصال
   خلال ثوانٍ بدل انتظار المهلة كاملة، ويميّز ConnectTimeout عن
   ReadTimeout تلقائياً)، والتقاط last_error() (نوع الاستثناء/رسالته/
   حالة HTTP وجسم الرد إن وُجدا) — مسحوب فوراً بعد كل نداء، لا تخمين.
2. silk_ai_judge: failure_reason()/_traced_call() يُدرجان تفصيل الفشل
   الفعلي (لا "مهلة أو خطأ شبكة" العامة) حين متاح.
3. silk_llm_runtime._parse_output: رد مشوَّه بند واحد بلا غلاف
   (findings/gaps/summary) يُعالَج كبند وحيد بدل تسريبه كـsummary خام؛
   ورد غير قابل للتفسير إطلاقاً لا يسرّب نصاً يشبه JSON أبداً.
4. silk_render: _strip_raw_json_leak/_strip_internal_plumbing ينظّفان
   ملخّص أي بعثة (لا risk_news فقط) قبل وصوله لأي سطح معروض للعميل.

لا شبكة ولا مفتاح حقيقي مطلوبان (نفس تقليد المستودع الهيرمتي).
Run:  python3 -m pytest tests/test_wave_p3_writer_diagnostics_and_json_leak.py -q
"""
import contextlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

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


# ── ١: مهلة الاتصال/القراءة المنفصلة + التقاط تفصيل الفشل الفعلي ─────────

def test_timeout_pair_splits_connect_and_read():
    import silk_llm_provider as lp

    assert lp.AnthropicProvider._timeout_pair(300) == (10.0, 300.0)
    assert lp.AnthropicProvider._timeout_pair(5) == (5.0, 5.0)  # لا اتصال أطول من الكل


def test_complete_passes_timeout_pair_to_requests_post():
    import silk_llm_provider as lp

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "end_turn", "content": []}

    def _fake_post(url, timeout, headers, json):
        captured["timeout"] = timeout
        return _Resp()

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("requests.post", side_effect=_fake_post):
        lp.AnthropicProvider().complete("sys", "user", 100, "m", 300)

    assert captured["timeout"] == (10.0, 300.0)


def test_last_error_reset_at_start_of_every_call_no_stale_leak():
    """حارس عزل حالة: كل نداء يمسح last_error من أول سطر — نداء لاحق بلا
    مفتاح لا يُبقي تفصيل فشل من نداء سابق غير ذي صلة (خطر تسريب حقيقي
    عبر contextvar مشترك خارج/داخل الاختبارات)."""
    import requests
    import silk_llm_provider as lp

    def _raise(*a, **kw):
        raise requests.exceptions.ReadTimeout("x")

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("requests.post", side_effect=_raise):
        lp.AnthropicProvider().complete("sys", "user", 100, "m", 300)
    assert lp.last_error() is not None

    with _env(ANTHROPIC_API_KEY=None):
        lp.AnthropicProvider().complete("sys", "user", 100, "m", 300)
    assert lp.last_error() is None


def test_last_error_captures_read_timeout_type_and_message():
    import requests
    import silk_llm_provider as lp

    def _raise(*a, **kw):
        raise requests.exceptions.ReadTimeout("Read timed out.")

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("requests.post", side_effect=_raise):
        out = lp.AnthropicProvider().complete("sys", "user", 100, "m", 300)

    assert out is None
    err = lp.last_error()
    assert err["type"] == "ReadTimeout"
    assert "timed out" in err["message"].lower()


def test_last_error_captures_connect_timeout_distinctly():
    """يميّز ConnectTimeout عن ReadTimeout تلقائياً — بلاغ حي: "Timeout"
    الغامضة لم تكن تكشف أيّ طوري الفشل وقع فعلياً."""
    import requests
    import silk_llm_provider as lp

    def _raise(*a, **kw):
        raise requests.exceptions.ConnectTimeout("Connection timed out.")

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("requests.post", side_effect=_raise):
        lp.AnthropicProvider().complete("sys", "user", 100, "m", 300)

    assert lp.last_error()["type"] == "ConnectTimeout"


def test_last_error_captures_http_status_and_response_body():
    """"إن كانت خطأ شبكة فأظهر الرد" — بلاغ حي: يلتقط حالة HTTP ومقتطف
    جسم الرد عند فشل raise_for_status."""
    import requests
    import silk_llm_provider as lp

    resp = MagicMock()
    resp.status_code = 529
    resp.text = '{"error": {"message": "Overloaded"}}'
    err = requests.exceptions.HTTPError("529 Server Error")
    err.response = resp

    def _fake_post(*a, **kw):
        r = MagicMock()
        r.raise_for_status.side_effect = err
        return r

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("requests.post", side_effect=_fake_post):
        lp.AnthropicProvider().complete("sys", "user", 100, "m", 300)

    detail = lp.last_error()
    assert detail["type"] == "HTTPError"
    assert detail["status_code"] == 529
    assert "Overloaded" in detail["response_body"]


def test_last_error_cleared_on_success():
    import silk_llm_provider as lp

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "ok"}]}

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("requests.post", return_value=_Resp()):
        out = lp.AnthropicProvider().complete("sys", "user", 100, "m", 300)

    assert out == "ok"
    assert lp.last_error() is None


def test_complete_tools_also_captures_last_error():
    import requests
    import silk_llm_provider as lp

    def _raise(*a, **kw):
        raise requests.exceptions.ReadTimeout("Read timed out.")

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("requests.post", side_effect=_raise):
        out = lp.AnthropicProvider().complete_tools("sys", [], None, 100, "m", 300)

    assert out is None
    assert lp.last_error()["type"] == "ReadTimeout"


# ── ٢: failure_reason()/_traced_call() يُدرجان التفصيل الفعلي ─────────────

def test_failure_reason_includes_actual_exception_type_when_available():
    import silk_ai_judge as aj

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_llm_provider.last_error",
               return_value={"type": "ReadTimeout", "message": "Read timed out."}):
        reason = aj.failure_reason()

    assert "مفتاح" not in reason
    assert "ReadTimeout" in reason
    assert "Read timed out" in reason


def test_failure_reason_falls_back_to_generic_message_without_last_error():
    import silk_ai_judge as aj

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_llm_provider.last_error", return_value=None):
        reason = aj.failure_reason()

    assert "مهلة أو خطأ شبكة" in reason


def test_traced_call_records_error_detail_in_trace_event(tmp_path):
    import silk_ai_judge as aj
    import silk_trace

    with _env(ANTHROPIC_API_KEY="test-key", SILK_TRACE_DIR=str(tmp_path)), \
         patch("silk_ai_judge._call", return_value=None), \
         patch("silk_llm_provider.last_error",
               return_value={"type": "ReadTimeout",
                            "message": "Read timed out. (read timeout=300)"}):
        out = aj.write_reviewed_report(
            {}, "خلاصة", {"verdict": "WATCH"}, "تمور", "هولندا",
            trace_id="t-evidence")

    assert out["report"] is None
    assert "ReadTimeout" in out["failure_reason"]
    events = silk_trace.read_trace("t-evidence", dir_path=str(tmp_path))
    assert events[0]["error_type"] == "ReadTimeout"
    assert "read timeout=300" in events[0]["error_message"]


# ── ٣: _parse_output لا يسرّب JSON خاماً كملخّص ────────────────────────────

def _registry_with(did, value=100.0, note="n"):
    from silk_data_layer import DataPoint
    return {did: DataPoint(value, "src", 0.8, note)}


def test_parse_output_wraps_bare_claim_object_as_single_finding():
    """رد مشوَّه (بند واحد بلا غلاف findings/gaps/summary) — بلاغ حي
    risk_news: كان يُرفَض كاملاً فيتسرّب نصاً خاماً؛ الآن يُعالَج كبند
    عادي (يُقبل إن استُشهِد بمعرّف صالح)."""
    import silk_llm_runtime as rt

    text = json.dumps({"claim": "الاستقرار السياسي معتدل نسبياً",
                       "datapoint_ids": ["dp1"], "confidence": 0.7},
                      ensure_ascii=False)
    out = rt._parse_output(text, _registry_with("dp1"))

    assert out["summary"] == ""  # لا نص خام يتسرّب كملخّص
    assert len(out["findings"]) == 1
    assert out["findings"][0]["claim"] == "الاستقرار السياسي معتدل نسبياً"
    assert out["findings"][0]["datapoint_ids"] == ["dp1"]


def test_parse_output_drops_bare_claim_object_without_valid_citation():
    import silk_llm_runtime as rt

    text = json.dumps({"claim": "ادّعاء بلا استشهاد صالح"}, ensure_ascii=False)
    out = rt._parse_output(text, {})

    assert out["findings"] == []
    assert len(out["dropped"]) == 1
    assert out["summary"] == ""  # لا تسريب حتى عند الإسقاط


def test_parse_output_json_shaped_garbage_never_leaks_into_summary():
    import silk_llm_runtime as rt

    # JSON مشوَّه (فاصلة زائدة) يبدأ بـ{ لكنه لا يُفسَّر إطلاقاً.
    text = '{"claim": "قيمة", "extra": ,}'
    out = rt._parse_output(text, {})

    assert out["findings"] == []
    assert out["summary"] == ""
    assert "{" not in out["summary"]


def test_parse_output_array_shaped_garbage_never_leaks_into_summary():
    import silk_llm_runtime as rt

    out = rt._parse_output('[{"claim": "x"}, {"claim": "y"',  {})
    assert out["summary"] == ""
    assert "[" not in out["summary"] and "{" not in out["summary"]


def test_parse_output_non_json_prose_failure_keeps_short_debug_snippet():
    """فشل تفسير نص نثري عادي (لا يشبه JSON) يبقى تلميحاً تشخيصياً قصيراً
    — القيمة التشخيصية محفوظة لما لا يخاطر بتسريب صيغة خام."""
    import silk_llm_runtime as rt

    out = rt._parse_output("عذراً، لا أستطيع المساعدة في هذا الطلب.", {})
    assert out["summary"] != ""
    assert "عذراً" in out["summary"]


def test_parse_output_still_extracts_wrapped_findings_normally():
    """حارس انحدار: المسار السعيد (رد مُغلَّف صحيح) غير متأثر بالتساهل
    الجديد — لا يُعامَل كبند وحيد لأنه يحمل مفتاح findings أصلاً."""
    import silk_llm_runtime as rt

    text = json.dumps({"findings": [{"claim": "قيمة", "datapoint_ids": ["dp1"],
                                     "confidence": 0.9}],
                       "gaps": [], "summary": "ok"}, ensure_ascii=False)
    out = rt._parse_output(text, _registry_with("dp1"))
    assert out["summary"] == "ok"
    assert len(out["findings"]) == 1


# ── ٤: طبقة العرض تنظّف ملخّص أي بعثة (لا risk_news فقط) ──────────────────

def test_strip_raw_json_leak_extracts_claim_field():
    from silk_render import _strip_raw_json_leak

    out = _strip_raw_json_leak(
        json.dumps({"claim": "لا توجد بيانات WITS"}, ensure_ascii=False))
    assert out == "لا توجد بيانات WITS"
    assert "{" not in out


def test_strip_raw_json_leak_unparseable_shows_generic_message():
    from silk_render import _strip_raw_json_leak

    out = _strip_raw_json_leak('{"claim": "x", "broken": ,}')
    assert "{" not in out
    assert out  # رسالة عربية مقروءة، ليست فارغة


def test_strip_raw_json_leak_leaves_normal_text_untouched():
    from silk_render import _strip_raw_json_leak

    clean = "الاستقرار السياسي معتدل وفق البنك الدولي."
    assert _strip_raw_json_leak(clean) == clean


def test_strip_raw_json_leak_passthrough_on_empty():
    from silk_render import _strip_raw_json_leak
    assert _strip_raw_json_leak(None) is None
    assert _strip_raw_json_leak("") == ""


_ALL_MISSION_KEYS = (
    "pricing_scout", "consumer_culture", "trade_flow", "demographics_economy",
    "competitors", "customs_requirements", "tariffs_agreements", "logistics",
    "channels_importers", "demand_trends", "risk_news", "opportunity_gaps")


def test_no_raw_json_leaks_into_any_mission_summary_across_all_missions():
    """بلاغ حي — الطلب صراحة: اختبار يرفض تسرّب JSON خام لأي ملخّص، لا
    risk_news تحديداً. يبني عرضاً بكل البعثات الاثنتي عشرة، كل ملخّص
    JSON خام، ويتحقق أن لا واحداً يتسرّب."""
    from silk_render import build_view
    from silk_agents import AgentReport

    missions = {
        key: AgentReport(f"LLMAgent:{key}", [], True,
                         json.dumps({"claim": f"قيمة {key}"}, ensure_ascii=False))
        for key in _ALL_MISSION_KEYS
    }
    result = {
        "product": "تمور", "hs_code": "080410", "markets": [],
        "market": {"iso3": "NGA", "name_ar": "نيجيريا"},
        "deep_research": {
            "missions": missions,
            "analyst": {"report": AgentReport("A", [], True, ""),
                       "by_category": {}, "missing_categories": []},
            "verdict": {}, "report": {},
        },
    }
    view = build_view(result)
    dr = view["deep_research"]
    for key in _ALL_MISSION_KEYS:
        summary = dr["missions"][key]["summary"]
        assert "{" not in summary and "}" not in summary, \
            f"{key}: {summary!r}"
    limits_text = " ".join(dr["limits"])
    assert "{" not in limits_text and "}" not in limits_text


def test_quality_gate_raw_json_check_stays_silent_after_render_layer_fix():
    """حارس انحدار: بعد إصلاح طبقة العرض، بوابة الجودة (raw_json القائم
    أصلاً) لا تُطلَق على ملخّص بعثة كان JSON خاماً — لأنه صار نظيفاً فعلاً
    قبل وصوله للبوابة، لا مجرد "قابل للإصلاح" نظرياً."""
    import silk_quality_gate as qg
    from silk_render import build_view
    from silk_agents import AgentReport

    result = {
        "product": "تمور", "hs_code": "080410", "markets": [],
        "market": {"iso3": "NGA", "name_ar": "نيجيريا"},
        "deep_research": {
            "missions": {"risk_news": AgentReport(
                "LLMAgent:risk_news", [], True,
                json.dumps({"claim": "لا توجد بيانات"}, ensure_ascii=False))},
            "analyst": {"report": AgentReport("A", [], True, ""),
                       "by_category": {}, "missing_categories": []},
            "verdict": {}, "report": {},
        },
    }
    view = build_view(result)
    out = qg.run_quality_gate(view)
    checks = {f["check"] for f in out["findings"]}
    assert "raw_json" not in checks

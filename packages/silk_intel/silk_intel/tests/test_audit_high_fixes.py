"""أقفال إصلاحات النتائج العالية من docs/FULL_AUDIT_2026-07-15.md.

سبعة إصلاحات، كلٌّ باختباره المسمّى في التقرير:
  H1 regen لا يطمس تقريراً سابقاً ناجحاً بـnull.
  H2 قيم تقاطعات المحلل تُطهَّر قبل /brief و/ask.
  H3 ملاحظة /ask تُطهَّر.
  H4 رموز failure_reason (empty_response/stop_reason/سجلّات الخادم) تُعرَّب.
  H5 ذيل التشغيلة يتدهور تحت حارس إنفاق حين تستنفد البعثات السقف.
  H6 حدّ إنفاق دولاري يومي حقيقي مع SILK_PAID_DAILY_USD_CAP.
  H7 تنزيل .md يفحص r.ok.

هيرمتي بالكامل — لا شبكة، لا مفتاح حقيقي (نُطعِّم نداءات كلود).
"""
from __future__ import annotations

import contextlib
import os
import sys
import tempfile
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


def _client():
    from fastapi.testclient import TestClient
    import importlib
    import api
    importlib.reload(api)
    return TestClient(api.create_app()), sys.modules["api"]


# ═══ H4 — تعريب رموز failure_reason (وحدة، الأبسط) ═══════════════════════

def test_failure_reason_tokens_are_humanized_before_any_client_surface():
    from silk_render import _strip_internal_plumbing
    raw = ("فشل نداء كلود (empty_response: HTTP 200 بلا كتل نصية — "
           "stop_reason='max_tokens') — راجع سجلّات الخادم")
    out = _strip_internal_plumbing(raw)
    assert "empty_response" not in out
    assert "stop_reason" not in out and "max_tokens" not in out
    assert "راجع سجلّات الخادم" not in out
    assert "بلغ التوليد الحدّ الأقصى للطول" in out   # عُرِّب لا حُذِف فقط


# ═══ H2 — تطهير قيم تقاطعات المحلل في /brief (والـ/ask يرثها) ═════════════

def _research_result_with_leaky_analyst():
    def _dp(value, note=""):
        return {"value": value, "source": "تحليل", "confidence": 0.7,
                "note": note, "retrieved_at": "2026-07-15"}
    return {
        "product": "تمور", "hs_code": "080410",
        "market": {"name_ar": "هولندا", "name_en": "Netherlands", "iso3": "NLD"},
        "header": {"product": "تمور", "hs_code": "080410",
                   "target_market": "هولندا", "date": "2026-07-15"},
        "deep_research": {
            "verdict": {"verdict": "WATCH",
                        "ai": {"verdict": "WATCH", "reasoning": "مبني على الحقائق."}},
            "report": {"report": "## 1. تقرير", "unresolved_notes": [],
                       "failure_reason": ""},
            "analyst": {
                "summary": "ملخّص",
                "missing_categories": [],
                "by_category": {
                    "demand": [_dp("LLMMissionAgent: pricing_scout يقدّر الطلب dp7")],
                    "entry_door": [_dp("موزّع", note="[entry_door] عبر LLMAgent:channels_importers")],
                }},
            "missions": {}, "limits": [], "trace_id": "t"},
    }


def test_brief_analyst_values_are_sanitized():
    import silk_render
    view = silk_render.build_view(_research_result_with_leaky_analyst())
    dm = view["deep_research"]["analyst"]["by_category"]["demand"][0]
    # القيمة نفسها مُطهَّرة في المصدر (المستهلكون يرثونها).
    assert "LLMMissionAgent" not in dm["value"] and "dp7" not in dm["value"]
    ed_note = view["deep_research"]["analyst"]["by_category"]["entry_door"][0]["note"]
    assert "LLMAgent:" not in ed_note
    # والمختصر (يقرأ by_category) نظيف.
    brief = " ".join(view.get("brief") or [])
    assert "LLMMissionAgent" not in brief and "dp7" not in brief and "LLMAgent:" not in brief


# ═══ H3 — تطهير ملاحظة /ask ══════════════════════════════════════════════

def test_ask_note_is_sanitized():
    with _env(SILK_API_KEY="x", ANTHROPIC_API_KEY="k", SILK_RATE_LIMIT="0",
              SILK_USAGE_DB=os.path.join(tempfile.mkdtemp(), "u.db")):
        client, api = _client()
        found = {"product": "تمور", "deep_research": {"trace_id": "t"},
                 "market": {"name_en": "Netherlands"}}
        with mock.patch("silk_storage.get_analysis", return_value=found), \
             mock.patch("silk_ai_judge.answer_about_analysis", return_value=None), \
             mock.patch("silk_ai_judge.failure_reason",
                        return_value="فشل نداء كلود (empty_response: "
                                     "stop_reason='max_tokens') — راجع سجلّات الخادم"):
            r = client.post("/analyses/7/ask", json={"question": "؟"},
                            headers={"X-API-Key": "x"})
        assert r.status_code == 200
        note = r.json()["note"]
        assert "empty_response" not in note and "stop_reason" not in note
        assert "راجع سجلّات الخادم" not in note


# ═══ H1 — regen لا يطمس تقريراً سابقاً ناجحاً ════════════════════════════

def test_regen_writer_failure_preserves_prior_report():
    with _env(SILK_API_KEY="x", ANTHROPIC_API_KEY="k", SILK_RATE_LIMIT="0",
              SILK_USAGE_DB=os.path.join(tempfile.mkdtemp(), "u.db")):
        client, api = _client()
        prior = {"product": "تمور", "hs_code": "080410",
                 "market": {"name_en": "Netherlands"},
                 "deep_research": {"trace_id": "t", "analyst": {"report": {"summary": "s"}},
                                   "verdict": {"verdict": "GO"},
                                   "report": {"report": "## تقرير سابق ناجح"}}}
        saved = {"called": False}

        def _spy_save(*a, **k):
            saved["called"] = True

        with mock.patch("silk_storage.get_analysis", return_value=prior), \
             mock.patch("silk_storage.load_mission_checkpoints",
                        return_value={"trade_flow": object()}), \
             mock.patch("silk_ai_judge.write_reviewed_report",
                        return_value={"report": None, "review_cycles": 0,
                                      "unresolved_notes": [],
                                      "failure_reason": "فشل نداء كلود (empty_response)"}), \
             mock.patch("silk_storage.save_analysis", side_effect=_spy_save):
            r = client.post("/analyses/9/report", headers={"X-API-Key": "x"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("regenerated") is False        # لم يُعَد التوليد
        assert body.get("report") is None
        assert saved["called"] is False                 # السجل لم يُلمَس — التقرير السابق محفوظ
        assert "empty_response" not in (body.get("failure_reason") or "")  # مُطهَّر


# ═══ H5 — حارس إنفاق الذيل تحت استنفاد السقف ═════════════════════════════

def test_tail_is_governed_when_run_cap_hit():
    import silk_context
    captured = {}

    def _fake_deep_research(*a, **k):
        silk_context.count_data("llm_calls", 5)   # البعثات استنفدت السقف
        return {"reports": {}, "trace_id": "t"}

    def _fake_synth(*a, **k):
        captured["synth_with_ai"] = k.get("with_ai")
        return {"verdict": "WATCH", "confidence": 0.5}

    def _fake_writer(*a, **k):
        captured["writer_max_cycles"] = k.get("max_cycles")
        return {"report": "## تقرير", "review_cycles": 0, "unresolved_notes": []}

    with _env(SILK_API_KEY="x", ANTHROPIC_API_KEY="k", SILK_RATE_LIMIT="0",
              SILK_RESEARCH_MAX_LLM_CALLS="1",
              SILK_USAGE_DB=os.path.join(tempfile.mkdtemp(), "u.db")):
        client, api = _client()
        with mock.patch("silk_missions.deep_research", side_effect=_fake_deep_research), \
             mock.patch("silk_market_analyst.analyze_market",
                        return_value={"report": {"summary": "s"}, "by_category": {},
                                      "missing_categories": []}), \
             mock.patch("silk_market_analyst.to_synthesis_input",
                        return_value={"summary": "s"}), \
             mock.patch("silk_synthesis.synthesize", side_effect=_fake_synth), \
             mock.patch("silk_ai_judge.write_reviewed_report", side_effect=_fake_writer), \
             mock.patch("silk_storage.create_research_run", return_value=1), \
             mock.patch("silk_storage.save_analysis"), \
             mock.patch("silk_storage.mark_research_failed"):
            r = client.post("/research",
                            json={"product": "تمور", "market": "Netherlands",
                                  "hs_code": "080410", "persist": False},
                            headers={"X-API-Key": "x"})
        assert r.status_code == 200, r.text
        # الذيل تدهور: حَكَم التوليف بلا كلود، والكاتب بلا دورة تنقيح.
        assert captured["synth_with_ai"] is False
        assert captured["writer_max_cycles"] == 1
        assert r.json()["deep_research"]["budget_status"]["tail_degraded"] is True


# ═══ H6 — حدّ إنفاق دولاري يومي حقيقي ════════════════════════════════════

def test_research_daily_spend_is_bounded_by_cap():
    tmp = os.path.join(tempfile.mkdtemp(), "u.db")
    import silk_usage
    with _env(SILK_PAID_DAILY_USD_CAP="10", SILK_USAGE_DB=tmp):
        silk_usage.record_usd(8.0)
        assert silk_usage.usd_spent_today() == 8.0
        assert silk_usage.would_exceed_usd_cap(3.0) is True    # 8+3 > 10 → يمنع
        assert silk_usage.would_exceed_usd_cap(1.0) is False   # 8+1 ≤ 10 → يسمح
    # بلا سقف مضبوط → لا حدّ (توافق خلفي).
    with _env(SILK_PAID_DAILY_USD_CAP=None, SILK_USAGE_DB=tmp):
        assert silk_usage.would_exceed_usd_cap(9999.0) is False


def test_research_refuses_429_when_daily_usd_cap_exhausted():
    tmp = os.path.join(tempfile.mkdtemp(), "u.db")
    import silk_usage
    silk_usage.record_usd(9.5, path=tmp)      # قرب السقف
    with _env(SILK_API_KEY="x", ANTHROPIC_API_KEY="k", SILK_RATE_LIMIT="0",
              SILK_PAID_DAILY_USD_CAP="10", SILK_RESEARCH_EXPECTED_USD="3.0",
              SILK_USAGE_DB=tmp):
        client, api = _client()
        r = client.post("/research",
                        json={"product": "تمور", "market": "Netherlands"},
                        headers={"X-API-Key": "x"})
        assert r.status_code == 429
        assert "daily_usd_budget_exhausted" in r.text


# ═══ H6 (تشديد التزامن) — حجز الدولار ذرّي، لا سباق بين تشغيلتين ══════════

def test_usd_reserve_is_atomic_under_concurrency():
    # سباق TOCTOU الدولاري: N تشغيلة تحجز معًا بسقف يسع K فقط => بالضبط K تنجح
    # والدفتر لا يتجاوز السقف (الفحص والتسجيل معاملة واحدة BEGIN IMMEDIATE،
    # فلا تمرّ تشغيلتان متزامنتان قرب الحدّ معًا — نظير حارس التفعيلات الذرّي).
    import threading
    import silk_usage
    usage_db = os.path.join(tempfile.mkdtemp(), "u.db")
    n, cap, est = 8, 10.0, 3.0          # يسع ٣ تشغيلات (٩$ ≤ ١٠$)، الرابعة تتجاوز
    affordable = int(cap // est)         # = 3
    with _env(SILK_PAID_DAILY_USD_CAP=str(cap), SILK_USAGE_DB=usage_db):
        results = []
        barrier = threading.Barrier(n)   # انطلاقة متزامنة لكشف السباق

        def _reserve_one():
            barrier.wait()
            results.append(silk_usage.try_reserve_usd(est, usage_db))

        threads = [threading.Thread(target=_reserve_one) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(results) == affordable                    # بالضبط بقدر ما يسعه السقف
        spent = silk_usage.usd_spent_today(usage_db)
        assert spent <= cap                                  # لا تجاوز مسجَّل
        assert spent == affordable * est


# ═══ H6 (دقّة) — دفتر الدولار يحتسب كل محاولات تصعيد سقف الكاتب ═══════════

def test_usd_ledger_includes_all_escalation_attempts():
    # التسوية تحتسب رموز *كل* محاولة تصعيد (لا الأولى فقط): كل ردّ HTTP يسجّل
    # رموزه في llm_usage (silk_llm_provider._record_usage قبل فحص الاقتطاع)،
    # والعدّاد يُقرأ بعد اكتمال الذيل، فتعكس التكلفة المُصالَحة المحاولات كلها.
    import silk_context
    import silk_llm_provider
    import silk_ai_judge
    from silk_pricing import estimate_cost_usd

    class _EscalatingProvider:
        def __init__(self):
            self.calls = 0

        def complete(self, system, user, max_tokens, model, timeout):
            self.calls += 1
            silk_context.record_llm_usage(model, 1000, 500)   # كل محاولة تسجّل رموزها
            if self.calls <= 2:                               # أول محاولتين مقتطعتان => تصعيد
                silk_llm_provider._last_stop_reason.set("max_tokens")
                return "## 1. مقتطع"
            silk_llm_provider._last_stop_reason.set("end_turn")
            return "## تقرير كامل"

        def complete_tools(self, *a, **k):
            return None

    fake = _EscalatingProvider()
    # اجعل عدّاد المحاولات هو القيد الملزِم لا سقف الرموز الصلب (كي يظهر تصعيد
    # من ٣ محاولات صراحة): سقف ابتدائي منخفض وسقف أعلى واسع.
    with _env(ANTHROPIC_API_KEY="k"), \
         mock.patch.object(silk_ai_judge, "_WRITER_MAX_TOKENS", 1000), \
         mock.patch.object(silk_ai_judge, "_MAX_TOKENS_CEILING", 100000):
        silk_llm_provider._provider_instance = fake
        try:
            silk_context.begin_data_counter()
            out = silk_ai_judge.deep_report(
                {}, "ملخّص", {"verdict": "WATCH"}, "تمور", "Netherlands")
            usage = (silk_context.data_counter() or {}).get("llm_usage", {})
        finally:
            silk_llm_provider.reset_provider()
    assert out                                                # أُنتِج تقرير رغم الاقتطاع المتكرّر
    assert fake.calls == 3                                    # تصعيد فعلي — ٣ محاولات
    row = usage.get(silk_ai_judge._MODEL, {})
    assert row.get("input_tokens") == 3000                   # المحاولات الثلاث مجموعة، لا واحدة
    assert row.get("output_tokens") == 1500
    # والتكلفة الدولارية (هي ما يُصالِح الدفتر عبر reconcile_usd) تعكس الثلاث.
    three = estimate_cost_usd(usage)["total_usd"]
    one = estimate_cost_usd(
        {silk_ai_judge._MODEL: {"input_tokens": 1000, "output_tokens": 500}}
    )["total_usd"]
    assert one > 0 and three == pytest.approx(3 * one)


# ═══ H7 — تنزيل .md يفحص r.ok ════════════════════════════════════════════

def test_md_download_guards_response_ok():
    html = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web", "index.html"), encoding="utf-8").read()
    md_lines = [ln for ln in html.splitlines()
                if "report.md" in ln and "fetch(" in ln]
    assert md_lines, "لم يُعثر على نداء تنزيل .md"
    # الثابت: فحص r.ok قبل استعمال الجسم. الصياغة تطوّرت من `throw` عارية
    # إلى `dlFail(r)` (تقرأ جسم الخطأ وتعرض تفصيله — عائلة 501 الثالثة،
    # LESSONS البند ١١) — كلاهما يحقّق الحارس؛ الحرفية القديمة كانت أضيق
    # من الثابت المقصود.
    assert "if(!r.ok)" in md_lines[0], md_lines[0]
    assert ("throw" in md_lines[0] or "dlFail(r)" in md_lines[0]), md_lines[0]

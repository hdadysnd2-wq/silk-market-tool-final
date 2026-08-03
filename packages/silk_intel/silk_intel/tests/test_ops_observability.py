"""أقفال ITEM 5 (خدمة ذاتية للمشغّل، تدقيق 2026-07-15).

يغطّي:
  5أ  GET /analyses/{id}?economics=1 — ملخّص اقتصاد التشغيلة (llm_usage/
      mission_usage/cost_usd_by_mission #96/العدّادات/التكلفة)، تشغيلة قديمة
      بلا mission_usage تعرض فجوة معلنة لا خطأ، والملاحظة الحرّة مُطهَّرة.
  5ب  GET /ops/last-errors — آخر N خطأ تشغيلي (تصدير/كاتب/حجز)؛ **كل الأسباب
      مُطهَّرة قبل التخزين** — أقفال عدائية بسلاسل الإنتاج الحرفية نفسها
      (empty_response/stop_reason='max_tokens'/راجع سجلّات الخادم/
      LLMMissionAgent: ...) للتأكّد أنها لا تصل هذه النقطة إطلاقاً.

هيرمتي بالكامل — لا شبكة، لا مفتاح حقيقي.
Run:  python3 -m pytest tests/test_ops_observability.py -q
"""
from __future__ import annotations

import contextlib
import os
import sys
import tempfile
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


def _client():
    from fastapi.testclient import TestClient
    import importlib
    import api
    importlib.reload(api)
    return TestClient(api.create_app()), sys.modules["api"]


# ═══ 5أ — GET /analyses/{id}?economics=1 ═══════════════════════════════════

def _research_blob_with_economics(mission_usage=None, cost_by_mission=None,
                                  note=""):
    return {
        "product": "تمور", "hs_code": "080410",
        "market": {"iso3": "NLD", "name_en": "Netherlands", "name_ar": "هولندا"},
        "markets": [],
        "deep_research": {"missions": {}, "analyst": {}, "verdict": {},
                          "report": {"report": "## تقرير"}, "trace_id": "t"},
        "data_economics": {
            "llm_calls": 38, "tool_calls": 61, "store_hits": 5,
            "cache_hits": 2, "live_fetches": 12,
            "llm_usage": {"claude-opus-4-8": {"input_tokens": 100000,
                                              "output_tokens": 20000}},
            "mission_usage": mission_usage or {},
            "cost_usd_estimate": 2.1,
            "cost_usd_by_model": {"claude-opus-4-8": 2.1},
            "cost_usd_by_mission": cost_by_mission or {},
            "cost_unpriced_models": [],
            "note": note or "38 نداء كلود، 61 نداء أداة، 7 قراءة خُدمت من "
                            "المخزن/ذاكرة الطلبات",
        },
    }


def test_economics_flag_returns_focused_summary_not_full_blob():
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0"):
        client, api = _client()
        blob = _research_blob_with_economics(
            mission_usage={"pricing_scout": {"claude-opus-4-8":
                                             {"input_tokens": 5000,
                                              "output_tokens": 1000}}},
            cost_by_mission={"pricing_scout": 0.15})
        with mock.patch("silk_storage.get_analysis", return_value=blob):
            r = client.get("/analyses/7?economics=1",
                           headers={"X-API-Key": "x"})
        assert r.status_code == 200
        body = r.json()
        assert body["analysis_id"] == 7
        assert body["llm_calls"] == 38 and body["tool_calls"] == 61
        assert body["cost_usd_estimate"] == 2.1
        assert body["mission_usage"]["pricing_scout"]["claude-opus-4-8"][
            "input_tokens"] == 5000
        assert body["cost_usd_by_mission"]["pricing_scout"] == 0.15
        assert body["mission_usage_available"] is True
        # مُركَّز — لا يحمل deep_research/markets الكاملة (البلوب الكامل).
        assert "deep_research" not in body and "markets" not in body


def test_economics_flag_declares_gap_for_run_predating_mission_attribution():
    """تشغيلة سابقة لـ#96 — mission_usage/cost_usd_by_mission غائبان في
    المخزَّن؛ فجوة معلنة صريحة (mission_usage_available=False)، لا خطأ 500،
    لا اختلاق رقم."""
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0"):
        client, api = _client()
        blob = _research_blob_with_economics()  # mission_usage={} افتراضياً
        del blob["data_economics"]["mission_usage"]      # غائب كلياً، لا فارغ فقط
        del blob["data_economics"]["cost_usd_by_mission"]
        with mock.patch("silk_storage.get_analysis", return_value=blob):
            r = client.get("/analyses/9?economics=1",
                           headers={"X-API-Key": "x"})
        assert r.status_code == 200
        body = r.json()
        assert body["mission_usage"] == {} and body["cost_usd_by_mission"] == {}
        assert body["mission_usage_available"] is False
        assert body["llm_calls"] == 38                   # الحقول الأخرى سليمة


def test_without_economics_flag_full_blob_still_returned_unchanged():
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0"):
        client, api = _client()
        blob = _research_blob_with_economics()
        with mock.patch("silk_storage.get_analysis", return_value=blob):
            r = client.get("/analyses/7", headers={"X-API-Key": "x"})
        assert r.status_code == 200
        assert r.json() == blob                          # توافق خلفي كامل


def test_economics_flag_404s_for_unknown_analysis():
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0"):
        client, api = _client()
        with mock.patch("silk_storage.get_analysis", return_value=None):
            r = client.get("/analyses/999?economics=1",
                           headers={"X-API-Key": "x"})
        assert r.status_code == 404


def test_economics_flag_requires_auth():
    with _env(SILK_API_KEY="secret", SILK_RATE_LIMIT="0"):
        client, api = _client()
        r = client.get("/analyses/7?economics=1")
        assert r.status_code == 401


def test_economics_note_field_is_sanitized():
    """الملاحظة الحرّة (مبنيّة خادمياً لكن قد تحمل سباكة مسرَّبة من مصدر
    آخر) تمرّ عبر نفس مُطهِّر H2/H4 القائم — دفاع بالعمق."""
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0"):
        client, api = _client()
        blob = _research_blob_with_economics(
            note="LLMMissionAgent: pricing_scout استهلك 38 نداء dp7")
        with mock.patch("silk_storage.get_analysis", return_value=blob):
            r = client.get("/analyses/7?economics=1",
                           headers={"X-API-Key": "x"})
        note = r.json()["note"]
        assert "LLMMissionAgent" not in note and "dp7" not in note


# ═══ 5ب — GET /ops/last-errors ══════════════════════════════════════════════

def test_ops_last_errors_requires_auth():
    with _env(SILK_API_KEY="secret", SILK_RATE_LIMIT="0"):
        client, api = _client()
        r = client.get("/ops/last-errors")
        assert r.status_code == 401


def test_ops_last_errors_returns_recorded_entries_newest_first():
    import silk_ops_log
    db = os.path.join(tempfile.mkdtemp(), "ops.db")
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0", SILK_OPS_LOG_DB=db):
        client, api = _client()
        silk_ops_log.record_error("export_failure", "أولاً", path=db)
        silk_ops_log.record_error("writer_failure", "ثانياً", path=db)
        r = client.get("/ops/last-errors", headers={"X-API-Key": "x"})
        assert r.status_code == 200
        errors = r.json()["errors"]
        assert len(errors) == 2
        assert errors[0]["reason"] == "ثانياً"            # الأحدث أولاً
        assert errors[0]["kind"] == "writer_failure"


def test_ops_last_errors_respects_n_param():
    import silk_ops_log
    db = os.path.join(tempfile.mkdtemp(), "ops.db")
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0", SILK_OPS_LOG_DB=db):
        client, api = _client()
        for i in range(5):
            silk_ops_log.record_error("export_failure", f"خطأ {i}", path=db)
        r = client.get("/ops/last-errors?n=2", headers={"X-API-Key": "x"})
        assert len(r.json()["errors"]) == 2


def test_ops_last_errors_empty_when_nothing_recorded():
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0",
              SILK_OPS_LOG_DB=os.path.join(tempfile.mkdtemp(), "ops.db")):
        client, api = _client()
        r = client.get("/ops/last-errors", headers={"X-API-Key": "x"})
        assert r.status_code == 200 and r.json()["errors"] == []


# ── الأقفال العدائية: الأسباب الثلاثة كلها مُطهَّرة قبل وصول /ops/last-errors ──

def test_export_failure_reason_sanitized_before_ops_log():
    """docx 501 مضمون (الحارس مُغلَّف بحيث يرفض دوماً برسالة تحمل شظية
    تسريب خام لا يلتقطها مُطهِّر السباكة العام — «algorithm_language:
    «درجة الثقة»» عربية أصلاً، لا EN يُعرَّب) — يُسجَّل بسبب ثابت عام لا
    نص الاستثناء الخام؛ ردّ الـHTTP نفسه يبقى يحمل str(e) كاملاً كالمعتاد."""
    # §0 (حزمة الفكس v2.1): تصدير العميل يمرّ ببوابة الجودة أولاً — هذا
    # الاختبار يتحقّق من مسار فشل *لاحق* (render_client_docx يرفع RuntimeError
    # بتسريب)، فتقرير المدوّنة هنا يجب أن يكون كاملاً (١١ قسماً) كي يمرّ
    # ببوابة الجودة (لا 409 حجب) ويصل فعلاً إلى render_client_docx المموَّه.
    from tools.canonical_netherlands import REPORT_TEXT
    db = os.path.join(tempfile.mkdtemp(), "ops.db")
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0", SILK_OPS_LOG_DB=db):
        client, api = _client()
        blob = {"product": "تمور", "hs_code": "080410",
               "market": {"name_en": "Netherlands"}, "markets": [],
               "deep_research": {
                   "missions": {}, "analyst": {}, "verdict": {},
                   "report": {"report": REPORT_TEXT},
                   "trace_id": "t"}}
        leak = ("تصدير العميل يحوي مصطلحات ممنوعة — رُفض التوليد: "
               "algorithm_language: «درجة الثقة» LLMMissionAgent: pricing_scout")
        with mock.patch("silk_storage.get_analysis", return_value=blob), \
             mock.patch("silk_reports.render_client_docx",
                        side_effect=RuntimeError(leak)):
            r = client.get("/analyses/9/report.docx", headers={"X-API-Key": "x"})
        assert r.status_code == 501
        assert leak in r.text                              # الردّ نفسه لم يتغيّر (سلوك قائم)
        errs = client.get("/ops/last-errors", headers={"X-API-Key": "x"}).json()["errors"]
        assert errs and errs[0]["kind"] == "export_failure"
        reason = errs[0]["reason"]
        # لا نص الاستثناء الخام إطلاقاً — رسالة ثابتة عامة بدلاً من مطاردة
        # كل شظية تسريب محتملة بتعبير نمطي.
        assert "LLMMissionAgent" not in reason
        assert "درجة الثقة" not in reason and "algorithm_language" not in reason
        assert leak not in reason


def test_writer_failure_reason_sanitized_before_ops_log():
    """بلاغ حي: failure_reason خام يحمل empty_response/stop_reason='max_
    tokens'/راجع سجلّات الخادم — يجب ألّا يصل أيٌّ منها /ops/last-errors."""
    db = os.path.join(tempfile.mkdtemp(), "ops.db")
    raw_reason = ("فشل نداء كلود (empty_response: HTTP 200 بلا كتل نصية — "
                 "stop_reason='max_tokens') — راجع سجلّات الخادم")
    with _env(SILK_API_KEY="x", ANTHROPIC_API_KEY="k", SILK_RATE_LIMIT="0",
              SILK_OPS_LOG_DB=db,
              SILK_USAGE_DB=os.path.join(tempfile.mkdtemp(), "u.db")):
        client, api = _client()
        prior = {"product": "تمور", "hs_code": "080410",
                 "market": {"name_en": "Netherlands"},
                 "deep_research": {"trace_id": "t",
                                   "analyst": {"report": {"summary": "s"}},
                                   "verdict": {"verdict": "GO"},
                                   "report": {"report": "## تقرير سابق ناجح"}}}
        with mock.patch("silk_storage.get_analysis", return_value=prior), \
             mock.patch("silk_storage.load_mission_checkpoints",
                        return_value={"trade_flow": object()}), \
             mock.patch("silk_ai_judge.write_reviewed_report",
                        return_value={"report": None, "review_cycles": 0,
                                      "unresolved_notes": [],
                                      "failure_reason": raw_reason}), \
             mock.patch("silk_storage.save_analysis"):
            client.post("/analyses/11/report", headers={"X-API-Key": "x"})
        r = client.get("/ops/last-errors", headers={"X-API-Key": "x"})
        errors = r.json()["errors"]
        assert errors and errors[0]["kind"] == "writer_failure"
        reason = errors[0]["reason"]
        assert "empty_response" not in reason
        assert "stop_reason" not in reason and "max_tokens" not in reason
        assert "راجع سجلّات الخادم" not in reason
        assert "بلغ التوليد الحدّ الأقصى للطول" in reason   # عُرِّب لا حُذِف


def test_reservation_refused_recorded_with_cap_state():
    """رفض حجز 429 (سقف التفعيلات المدفوعة) يُسجَّل بحالة السقف — نص خادمي
    بحت، سليم بداهةً، لكن نتحقّق من التسجيل والسياق صراحة."""
    db = os.path.join(tempfile.mkdtemp(), "ops.db")
    usage_db = os.path.join(tempfile.mkdtemp(), "usage.db")
    with _env(SILK_API_KEY=None, SILK_PAID_DAILY_CAP="0", SILK_RATE_LIMIT="0",
              SILK_USAGE_DB=usage_db, SILK_OPS_LOG_DB=db):
        client, api = _client()
        r = client.post("/deepen", json={"product": "تمور",
                                         "with_localprice": True})
        assert r.status_code == 429
    with _env(SILK_API_KEY="x", SILK_RATE_LIMIT="0", SILK_OPS_LOG_DB=db):
        client, api = _client()
        rr = client.get("/ops/last-errors", headers={"X-API-Key": "x"})
        errors = rr.json()["errors"]
        assert errors and errors[0]["kind"] == "reservation_refused"
        assert errors[0]["context"] is not None


# ═══ silk_ops_log — وحدة التخزين نفسها ══════════════════════════════════════

def test_ops_log_ring_buffer_caps_at_configured_size():
    import silk_ops_log
    db = os.path.join(tempfile.mkdtemp(), "ops.db")
    with _env(SILK_OPS_LOG_CAP="3"):
        for i in range(10):
            silk_ops_log.record_error("export_failure", f"خطأ {i}", path=db)
        rows = silk_ops_log.last_errors(100, path=db)
        assert len(rows) == 3
        assert rows[0]["reason"] == "خطأ 9"               # الأحدث بقي
        assert rows[-1]["reason"] == "خطأ 7"               # الأقدم حُذف


def test_ops_log_write_failure_never_raises(monkeypatch):
    import silk_ops_log
    with mock.patch("silk_ops_log._connect",
                    side_effect=RuntimeError("disk full")):
        silk_ops_log.record_error("export_failure", "test")  # لا استثناء


def test_ops_log_read_returns_empty_list_not_exception_without_db():
    import silk_ops_log
    assert silk_ops_log.last_errors(
        10, path=os.path.join(tempfile.mkdtemp(), "never_created.db")) == []


def test_ops_log_context_roundtrips_as_json():
    import silk_ops_log
    db = os.path.join(tempfile.mkdtemp(), "ops.db")
    silk_ops_log.record_error("reservation_refused", "سقف بلغ حدّه",
                              context={"expected_usd": 3.0, "spent_today_usd": 8.5},
                              path=db)
    rows = silk_ops_log.last_errors(1, path=db)
    assert rows[0]["context"] == {"expected_usd": 3.0, "spent_today_usd": 8.5}

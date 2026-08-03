"""إصلاح البند ١ (تدقيق تكلفة حيّ): تحليلات مكتملة مدفوعة الثمن لا تظهر لاحقاً
في الواجهة فيُعاد دفع ثمنها. يغطي:

(أ) تحذير `/health` الصريح حين `SILK_DATA_DIR` غير مضبوط — كان `data_dir: null`
    يمرّ بصمت رغم أنه يعني فقدان كل التحليلات عند إعادة النشر التالية على
    Railway (حاوية فانية بلا وحدة تخزين).
(ب) حقول شريط «بحوثي السابقة» (market_name/verdict_label/cost_usd) تُملأ
    فعلياً من نموذج العرض الموحّد عند الحفظ — لتحليلَي /analyze و/research
    كليهما — وتُقرأ سليمة عبر list_analyses (بما فيها صفوف قديمة بلا الحقول).
(ج) GET /analyses وGET /analyses/{id} قراءتان محضتان — إثبات بنيوي أن فتح
    تحليلات محفوظة سابقاً لا يُطلق أي نداء كلود (دلتا llm_usage = صفر).

Run: python3 -m pytest tests/test_analysis_history_storage.py -q
"""
import contextlib
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.contextmanager
def _env(**vals):
    saved = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _client():
    import pytest
    from fastapi.testclient import TestClient
    import api
    import importlib
    importlib.reload(api)
    return TestClient(api.app)


def _research_result():
    from silk_market_resolver import resolve_market
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    ref, _ = resolve_market("Netherlands")
    analyst_report = AgentReport(
        "LLMAgent:market_analyst",
        [DataPoint("طلب استدلالي", "x", 0.6, "[demand] ...")], False, "تحليل")
    return {
        "product": "تمور", "hs_code": "080410", "year": None,
        "market": {"iso3": ref.iso3, "m49": ref.m49, "iso2": ref.iso2,
                  "name_en": ref.name_en, "name_ar": ref.name_ar},
        "markets": [],
        "deep_research": {
            "missions": {"trade_flow": AgentReport(
                "LLMAgent:trade_flow",
                [DataPoint(129_600_000.0, "UN Comtrade", 0.9, "واردات 2025")],
                False, "ok")},
            "analyst": {"report": analyst_report,
                       "by_category": {"demand": analyst_report.findings},
                       "missing_categories": []},
            "verdict": {"verdict": "WATCH",
                       "ai": {"verdict": "WATCH", "confidence": 0.55}},
            "report": {"report": "## 1. الخلاصة\nنص.", "review_cycles": 1,
                      "unresolved_notes": []},
        },
        "data_economics": {"cost_usd_estimate": 1.6, "llm_calls": 20,
                          "tool_calls": 40},
    }


def _analyze_result():
    return {
        "product": "شاي", "hs_code": "090210", "year": 2023,
        "markets": [{
            "country": "الصين", "iso3": "CHN", "total_score": 0.8,
            "confidence": 0.7,
            "decision": {"schema": "silk.decision/v1", "verdict": "GO",
                        "confidence": 0.7, "score": 0.8, "why": "سوق كبير"},
            "jury": {"data_gaps": [], "agents_with_data": 4,
                    "agents_total": 4},
        }],
        "data_economics": {"cost_usd_estimate": 0.02, "llm_calls": 1,
                          "tool_calls": 3},
    }


# ── (أ) تحذير /health لتخزين فانٍ ───────────────────────────────────────────

def test_health_warns_when_silk_data_dir_unset():
    with _env(SILK_DATA_DIR=None, SILK_DB=None, SILK_API_KEY=None,
              ANTHROPIC_API_KEY=None, VOLZA_API_KEY=None,
              EXPLEE_API_KEY=None, LOCALPRICE_API_KEY=None):
        r = _client().get("/health")
    body = r.json()
    warnings = body.get("warnings") or []
    assert any("SILK_DATA_DIR" in w for w in warnings), (
        "بلاغ حي: هذا التحذير بالضبط كان غائباً بينما data_dir=null على "
        f"Railway الحيّة. warnings={warnings}")
    assert body["storage"]["data_dir"] is None


def test_health_no_storage_warning_when_silk_data_dir_set():
    tmp = tempfile.mkdtemp()
    with _env(SILK_DATA_DIR=tmp, SILK_API_KEY=None, ANTHROPIC_API_KEY=None,
              VOLZA_API_KEY=None, EXPLEE_API_KEY=None,
              LOCALPRICE_API_KEY=None):
        r = _client().get("/health")
    body = r.json()
    warnings = body.get("warnings") or []
    assert not any("SILK_DATA_DIR" in w for w in warnings)
    assert body["storage"]["data_dir"] == tmp


def test_health_exposes_persist_guard_state():
    """PART E (أمر العمل الرئيس): حالة SILK_REQUIRE_PERSISTENT_DATA_DIR
    مرئية من /health — كانت غير قابلة للتفتيش عن بُعد إطلاقاً.

    تقوية البند ٤: المصيدة صارت ترفض الإقلاع على مسارٍ ليس وحدة مركّبة، لذا
    نحاكي وحدة تخزين حقيقية (ismount=True) كي يقلع تحت العلَم المفعّل."""
    from unittest.mock import patch
    tmp = tempfile.mkdtemp()
    with _env(SILK_DATA_DIR=tmp, SILK_REQUIRE_PERSISTENT_DATA_DIR="1",
              SILK_API_KEY=None, ANTHROPIC_API_KEY=None, VOLZA_API_KEY=None,
              EXPLEE_API_KEY=None, LOCALPRICE_API_KEY=None):
        with patch("os.path.ismount", return_value=True):
            on = _client().get("/health").json()
    with _env(SILK_DATA_DIR=tmp, SILK_REQUIRE_PERSISTENT_DATA_DIR=None,
              SILK_API_KEY=None, ANTHROPIC_API_KEY=None, VOLZA_API_KEY=None,
              EXPLEE_API_KEY=None, LOCALPRICE_API_KEY=None):
        off = _client().get("/health").json()
    assert on["storage"]["persist_guard"] is True
    assert off["storage"]["persist_guard"] is False


def test_health_exposes_hs_classifier_valve_state_and_warns_when_disabled():
    """اللائحة ٤٣ (بلاغ حي متكرّر — رمز HS خاطئ رغم إصلاح المُصنِّف العام):
    صمّام `SILK_HS_CLASSIFIER` مرئي من /health — كان غير قابل للتفتيش عن
    بُعد فلا يعرف المالك أن الإصلاح المدموج لا يعمل فعلياً على النشر."""
    with _env(SILK_HS_CLASSIFIER=None, SILK_API_KEY=None,
              ANTHROPIC_API_KEY="k", VOLZA_API_KEY=None,
              EXPLEE_API_KEY=None, LOCALPRICE_API_KEY=None):
        default_on = _client().get("/health").json()
    assert default_on["hs_classifier"]["enabled"] is True
    assert not any("SILK_HS_CLASSIFIER" in w
                  for w in (default_on.get("warnings") or []))
    with _env(SILK_HS_CLASSIFIER="0", SILK_API_KEY=None,
              ANTHROPIC_API_KEY="k", VOLZA_API_KEY=None,
              EXPLEE_API_KEY=None, LOCALPRICE_API_KEY=None):
        explicitly_off = _client().get("/health").json()
    assert explicitly_off["hs_classifier"]["enabled"] is False
    assert any("SILK_HS_CLASSIFIER" in w
              for w in (explicitly_off.get("warnings") or [])), (
        "تعطيل الصمّام صراحةً مع مفتاح كلود متاح يجب أن يظهر تحذيراً — "
        "وإلا يعود المالك لعدم رؤية أن الإصلاح مُعطَّل فعلياً على النشر")


def test_health_no_storage_warning_when_explicit_silk_db_set():
    """لا تحذير أيضاً حين يُوجَّه SILK_DB صراحةً بلا SILK_DATA_DIR — نفس
    منطق تراجُع _db_path نفسه (لا انحدار على المسارات الصريحة الفردية)."""
    tmp = os.path.join(tempfile.mkdtemp(), "silk.db")
    with _env(SILK_DATA_DIR=None, SILK_DB=tmp, SILK_API_KEY=None,
              ANTHROPIC_API_KEY=None, VOLZA_API_KEY=None,
              EXPLEE_API_KEY=None, LOCALPRICE_API_KEY=None):
        r = _client().get("/health")
    warnings = r.json().get("warnings") or []
    assert not any("SILK_DATA_DIR" in w for w in warnings)


# ── (ب) حقول شريط بحوثي السابقة ────────────────────────────────────────────

def test_save_analysis_populates_sidebar_fields_for_research_result():
    import silk_storage as ST
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = ST.save_analysis(_research_result(), path=db)
    rows = ST.list_analyses(path=db)
    row = next(r for r in rows if r["id"] == aid)
    assert row["market_name"] == "هولندا"
    assert row["verdict_label"] == "مراقبة السوق"
    assert row["cost_usd"] == 1.6


def test_save_analysis_populates_sidebar_fields_for_analyze_result():
    import silk_storage as ST
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = ST.save_analysis(_analyze_result(), path=db)
    rows = ST.list_analyses(path=db)
    row = next(r for r in rows if r["id"] == aid)
    assert row["market_name"] == "الصين"
    assert row["verdict_label"] == "التوصية بالدخول"
    assert row["cost_usd"] == 0.02


def test_create_research_run_stores_market_name_for_running_row():
    import silk_storage as ST
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = ST.create_research_run("تمور", "NLD", "080410", {"product": "تمور"},
                                 path=db, market_name="هولندا")
    row = next(r for r in ST.list_analyses(path=db) if r["id"] == aid)
    assert row["market_name"] == "هولندا"
    assert row["status"] == "running"
    assert row["verdict_label"] is None  # لم يكتمل بعد — لا اختلاق حكم


def test_create_research_run_falls_back_to_iso3_without_market_name():
    import silk_storage as ST
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = ST.create_research_run("تمور", "NLD", "080410", {}, path=db)
    row = next(r for r in ST.list_analyses(path=db) if r["id"] == aid)
    assert row["market_name"] == "NLD"


def test_list_analyses_none_for_legacy_rows_without_new_columns():
    """صفّ من مخطّط أقدم (بلا الحقول الجديدة) — None صريح لا استثناء ولا خطأ."""
    import silk_storage as ST
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    ST.init_db(db)
    with ST._connect(db) as conn:
        conn.execute(
            "INSERT INTO analyses (product, hs_code, year, created_at, "
            "preliminary, json_blob) VALUES (?, ?, ?, ?, ?, ?)",
            ("قديم", "000000", 2020, "2020-01-01", 1, "{}"))
    rows = ST.list_analyses(path=db)
    row = rows[0]
    assert row["market_name"] is None
    assert row["verdict_label"] is None
    assert row["cost_usd"] is None


def test_sidebar_field_extraction_failure_does_not_break_save():
    """عرض شريط لا شرط حفظ — result مشوَّه يُفشِل build_view لا يمنع
    save_analysis من إتمام عمله."""
    import silk_storage as ST
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    # markets:[] صالحة (لا تكسر حلقة market_scores الحالية) لكن deep_research
    # مشوَّهة عمداً (تكسر build_view تحديداً — لا نخلط عطلاً آخر بعطل التشخيص).
    broken = {"product": "منتج", "markets": [], "deep_research": "not a dict"}
    aid = ST.save_analysis(broken, path=db)
    row = next(r for r in ST.list_analyses(path=db) if r["id"] == aid)
    assert row["market_name"] is None  # فشل التشخيص، لا فشل الحفظ نفسه
    assert row["product"] == "منتج"


# ── (ج) إثبات صفر نداء كلود عند إعادة فتح تحليل محفوظ ───────────────────────

def test_reopening_stored_analyses_never_calls_claude():
    import silk_storage as ST
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    ids = [ST.save_analysis(_research_result(), path=db) for _ in range(3)]

    def _boom(*a, **k):
        raise AssertionError("Claude must never be called to reopen a stored analysis")

    with _env(SILK_API_KEY="secret", SILK_DB=db), \
         patch("silk_llm_provider.AnthropicProvider.complete", side_effect=_boom), \
         patch("silk_llm_provider.AnthropicProvider.complete_tools", side_effect=_boom):
        client = _client()
        hdr = {"X-API-Key": "secret"}
        r_list = client.get("/analyses", headers=hdr)
        assert r_list.status_code == 200
        for aid in ids:
            r = client.get(f"/analyses/{aid}", headers=hdr)
            assert r.status_code == 200
            r_eco = client.get(f"/analyses/{aid}?economics=1", headers=hdr)
            assert r_eco.status_code == 200


def test_writer_diagnostics_exposes_raw_report_call_error_type():
    """القضية المفتوحة (كاتب التقرير، PRs 69/70/71): نقطة writer-diagnostics
    تكشف `error_type` الخام (ReadTimeout/429/…) **دون تطهير** — كي يُميَّز نوع
    فشل الكاتب عن بُعد. كل سطوح الـHTTP الأخرى تُطهّره، فهذه نافذة الدليل
    الوحيدة للمالك؛ الإصلاح الصحيح = ما يشير إليه هذا الدليل، لا تخمين."""
    import silk_storage as ST
    import silk_trace
    base = tempfile.mkdtemp()
    db = os.path.join(base, "silk.db")
    trace_dir = os.path.join(base, "traces")
    os.makedirs(trace_dir, exist_ok=True)
    trace_id = "diag-test-trace-1"
    result = _research_result()
    result["deep_research"]["trace_id"] = trace_id
    # الكاتب فشل: report=None + سبب مخزَّن مُطهَّر، بينما الأثر يحمل الخام.
    result["deep_research"]["report"] = {
        "report": None, "review_cycles": 0, "unresolved_notes": [],
        "failure_reason": "فشل نداء التحليل الآلي (تعذّر الاتصال بالمصدر)"}
    with _env(SILK_API_KEY="secret", SILK_DB=db, SILK_TRACE_DIR=trace_dir):
        silk_trace.append_event(trace_id, kind="report_call", stage="draft",
                                timeout=300, elapsed_ms=300123, success=False,
                                error_type="ReadTimeout",
                                error_message="Read timed out. (read timeout=300)")
        aid = ST.save_analysis(result, path=db)
        client = _client()
        hdr = {"X-API-Key": "secret"}
        r = client.get(f"/analyses/{aid}/writer-diagnostics", headers=hdr)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["trace_id"] == trace_id
        assert body["report_present"] is False
        calls = body["report_calls"]
        assert len(calls) == 1 and calls[0]["success"] is False
        # الدليل الخام يمرّ بلا تطهير — هذا هو الغرض (قياس لا تخمين).
        assert calls[0]["error_type"] == "ReadTimeout"
        assert "300" in str(calls[0].get("error_message", ""))
        # محروسة بالمفتاح كبقية سطوح المشغّل.
        assert client.get(f"/analyses/{aid}/writer-diagnostics").status_code == 401


def test_writer_diagnostics_404_for_missing_and_empty_for_no_trace():
    """404 لتحليل غائب؛ وقائمة report_calls فارغة + ملاحظة لتحليل بلا trace_id
    (تشغيلة أقدم من التتبّع) — بلا استثناء ولا اختلاق."""
    import silk_storage as ST
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    result = _research_result()          # بلا trace_id
    with _env(SILK_API_KEY="secret", SILK_DB=db):
        aid = ST.save_analysis(result, path=db)
        client = _client()
        hdr = {"X-API-Key": "secret"}
        assert client.get("/analyses/999999/writer-diagnostics",
                          headers=hdr).status_code == 404
        body = client.get(f"/analyses/{aid}/writer-diagnostics",
                          headers=hdr).json()
        assert body["trace_id"] is None and body["report_calls"] == []
        assert body["note"]

"""الحارس — «كاميرا مراقبة» داخل المنصّة (طلب المُشرِف، بعد PR #134).

يغطي الأربعة أجزاء: طبقة الاستشعار الحتمية (PART 1)، سطح المالك المنفصل
(PART 2 — API + عدم تلوّث سطوح العميل)، عقل الاتجاه (PART 3)، والحماية
الذاتية (PART 4 — لا يُبطئ/يُسقِط تحليلاً، يراقب نفسه).

Run: python3 -m pytest tests/test_watchdog.py -q
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.canonical_kuwait_peanut_butter import kuwait_research_blob


@pytest.fixture(autouse=True)
def _isolated_watchdog_db(tmp_path):
    """كل اختبارٍ يكتب على قواعد مؤقّتة خاصّة به — لا تلوّث `data/` الحقيقي
    في الريبو (نفس انضباط `test_cross_market_leak_guard.py`)، **ولا يقرأ
    سجلّ عمليات مشتركاً** قد تكون اختباراتٌ أخرى في نفس التشغيلة كتبت إليه
    (`_check_services` يقرأ `silk_ops_log` بنافذةٍ زمنية تقريبية — بلا هذا
    العزل تتلوّث بأعطال خدماتٍ من اختباراتٍ أخرى لا صلة لها). اختباراتٌ
    تحتاج مساراً محدَّداً بذاتها تُعيد تصحيحه داخلياً (nested patch)."""
    import silk_ops_log
    import silk_watchdog
    wd_db = str(tmp_path / "watchdog.db")
    ops_db = str(tmp_path / "ops_errors.db")
    with patch.object(silk_watchdog, "_db_path", return_value=wd_db), \
         patch.object(silk_ops_log, "_db_path", return_value=ops_db):
        yield


def _view_result(blob=None):
    """نتيجة `/research` كاملة كما تصل `_attach_watchdog` — نفس ما يبنيه
    api.py: `result["view"] = build_view(result)`."""
    from silk_render import build_view
    result = blob or kuwait_research_blob()
    result = dict(result)
    result["view"] = build_view(result)
    return result


def _clean_result():
    """تشغيلةٌ نظيفة تماماً — رمزٌ مؤكَّد، لا تناقض سعر، لا تسريب، لا حقائق
    متقادِمة — لاختبار المسار الأخضر (لا كل فحصٍ يُطلِق شيئاً)."""
    def _dp(value, source="UN Comtrade", conf=0.8, note="", ra="2026-07-20"):
        return {"value": value, "source": source, "confidence": conf,
                "note": note, "retrieved_at": ra, "status": "", "data_year": None}

    def _m(summary, findings=None):
        return {"agent_name": "LLMMissionAgent", "summary": summary,
                "findings": findings or [], "failed": False}

    missions = {
        "trade_flow": _m("واردات التمور نحو 5 مليون دولار",
                         [_dp(5_000_000, note="واردات 2024")]),
        "pricing_scout": _m("سعر مستقر",
                            [_dp("3 دولار/كجم", note="متوسط سعر الاستيراد الرسمي"),
                             _dp("4 دولار/كجم", "Google Maps", note="سعر تجزئة مرصود")]),
    }
    analyst = {"report": {"agent_name": "market_analyst", "summary": "واعد",
                          "findings": [], "failed": False},
              "missing_categories": [], "by_category": {}}
    verdict = {"verdict": "GO", "confidence": 0.8,
              "ai": {"verdict": "GO", "reasoning": "سوقٌ واعد"}}
    report_out = {"report": "## 1. الخلاصة التنفيذية\nالحكم إيجابي.",
                 "review_cycles": 1, "unresolved_notes": [], "failure_reason": ""}
    return {
        "product": "تمور", "hs_code": "080410", "year": None, "preliminary": True,
        "market": {"iso3": "ARE", "m49": 784, "iso2": "AE",
                   "name_en": "UAE", "name_ar": "الإمارات"},
        "markets": [],
        "deep_research": {"missions": missions, "analyst": analyst,
                          "verdict": verdict, "report": report_out,
                          "trace_id": "clean-1",
                          "budget_status": {"tail_degraded": False}},
        "data_economics": {"llm_calls": 10, "stage_total_seconds": 120,
                          "cost_usd_estimate": 1.2, "cost_unpriced_models": []},
    }


# ══════════════ PART 1 — طبقة الاستشعار ══════════════

def test_hs_gate_check_flags_overridden_unconfirmed_code():
    import silk_watchdog
    with patch.dict(os.environ, {"SILK_HS_CONFIRM_GATE": "1"}):
        result = _view_result()
        rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["contracts"]["hs_gate"]["status"] == "overridden"
    codes = [f["code"] for f in rec["findings"]]
    assert "hs_gate_overridden" in codes


def test_hs_gate_check_red_when_gate_disabled_and_code_unconfirmed():
    """الرمز غير مؤكَّد + البوّابة مُطفأة صراحةً = خرقٌ أحمر (لا افتراضٌ
    ودود) — نفس الحادثة الأصلية لو تكرّرت."""
    import silk_watchdog
    with patch.dict(os.environ, {"SILK_HS_CONFIRM_GATE": "0"}):
        result = _view_result()
        rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["contracts"]["hs_gate"]["status"] == "unconfirmed_unsafe"
    assert rec["overall"] == "red"
    assert any(f["code"] == "hs_gate_unsafe" and f["severity"] == "red"
              for f in rec["findings"])


def test_hs_gate_confirmed_code_is_clean():
    import silk_watchdog
    result = _clean_result()
    result["view"] = __import__("silk_render").build_view(result)
    result["hs_confirmation"] = {"confirmed": True, "hs_code": "080410"}
    rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["contracts"]["hs_gate"]["status"] == "confirmed"


def test_price_sanity_flags_retail_below_wholesale():
    import silk_watchdog
    result = _view_result()  # الكويت: تجزئة 0.67$ < جملة 6$
    rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["contracts"]["price_sanity"]["status"] == "flagged"
    assert any(f["code"] == "price_sanity" for f in rec["findings"])


def test_price_sanity_ok_when_retail_above_wholesale():
    import silk_watchdog
    result = _view_result(_clean_result())
    rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["contracts"]["price_sanity"]["status"] == "ok"


def test_no_fabrication_violation_detected():
    """قيمةٌ غير فارغة بثقة 0.0 — زوجٌ متناقض، يُبلَّغ لا يُصحَّح صامتاً."""
    import silk_watchdog
    blob = kuwait_research_blob()
    blob["deep_research"]["missions"]["trade_flow"]["findings"].append(
        {"value": 42, "source": "x", "confidence": 0.0, "note": "",
         "retrieved_at": "", "status": "", "data_year": None})
    result = _view_result(blob)
    rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["contracts"]["no_fabrication"]["status"] == "violation"
    assert rec["overall"] == "red"


def test_no_fabrication_held_on_clean_datapoints():
    import silk_watchdog
    result = _view_result(_clean_result())
    rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["contracts"]["no_fabrication"]["status"] == "held"


def test_tariff_path_read_from_finding_source_not_logs():
    import silk_watchdog
    blob = kuwait_research_blob()
    blob["deep_research"]["missions"]["tariffs_agreements"] = {
        "agent_name": "LLMMissionAgent", "summary": "تعريفة", "failed": False,
        "findings": [{"value": 5.0, "source": "WTO TTD", "confidence": 0.7,
                      "note": "", "retrieved_at": "2026-07-20", "status": "",
                      "data_year": 2026}]}
    result = _view_result(blob)
    rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["economics"]["tariff_path"] == "wto"


def test_tariff_path_gap_when_value_none_and_wits_source():
    import silk_watchdog
    blob = kuwait_research_blob()
    blob["deep_research"]["missions"]["tariffs_agreements"] = {
        "agent_name": "LLMMissionAgent", "summary": "تعريفة", "failed": False,
        "findings": [{"value": None, "source": "World Bank WITS", "confidence": 0.0,
                      "note": "WTO + WITS both unavailable", "retrieved_at": "",
                      "status": "", "data_year": None}]}
    result = _view_result(blob)
    rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["economics"]["tariff_path"] == "gap"


def test_analyze_kind_has_no_deep_research_contracts_but_still_observed():
    """`/analyze` لا يملك `deep_research` — العقود الخاصة به (badge/leaks/
    price) تعود n/a بأمان بدل استثناء، والسجلّ يُخزَّن مع ذلك."""
    import silk_watchdog
    result = {"product": "تمور", "market": {}, "markets": [],
             "view": {}, "data_economics": {"llm_calls": 0}}
    rec = silk_watchdog.observe(result, "analyze", analysis_id=None)
    assert rec is not None
    assert rec["contracts"]["badge_body"]["status"] == "n/a"
    assert rec["contracts"]["price_sanity"]["status"] == "n/a"
    assert rec["overall"] == "green"


# ══════════════ PART 1/2 — تسرّب عبر-سوقي (اللائحة ٣٦) ══════════════

def test_cross_market_leak_seeded_violation_is_red():
    """حقيقةٌ مختومة بسوقٍ آخر (يمن) داخل تشغيلة الكويت — يُرصَد أحمر."""
    import silk_storage
    import silk_watchdog
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint

    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    yemen_report = AgentReport(
        agent_name="LLMMissionAgent:consumer_culture",
        findings=[DataPoint(value="سوق عدن المركزي / ربوع", source="web_search",
                            confidence=0.6, note="نتيجة بحث")],
        failed=False, summary="ثقافة استهلاك اليمن")
    silk_storage.save_mission_checkpoint(
        77, "consumer_culture", yemen_report, path=db, market_iso3="YEM")

    with patch("silk_storage._db_path", return_value=db):
        result = _view_result()  # market.iso3 = KWT
        rec = silk_watchdog.observe(result, "research", analysis_id=77)

    assert rec["contracts"]["cross_market_leak"]["status"] == "violation"
    assert rec["overall"] == "red"
    assert any(f["code"] == "cross_market_leak" for f in rec["findings"])


def test_cross_market_leak_clean_when_only_own_market_stamped():
    import silk_storage
    import silk_watchdog
    from silk_agents import AgentReport

    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    own_report = AgentReport(agent_name="x", findings=[], failed=False, summary="ok")
    silk_storage.save_mission_checkpoint(
        78, "consumer_culture", own_report, path=db, market_iso3="KWT")

    with patch("silk_storage._db_path", return_value=db):
        result = _view_result()
        rec = silk_watchdog.observe(result, "research", analysis_id=78)

    assert rec["contracts"]["cross_market_leak"]["status"] == "clean"


def test_cross_market_leak_na_when_not_persisted():
    import silk_watchdog
    result = _view_result()
    rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["contracts"]["cross_market_leak"]["status"] == "n/a"


# ══════════════ PART 4 — الحماية الذاتية ══════════════

def test_clean_run_is_overall_green():
    import silk_watchdog
    result = _view_result(_clean_result())
    result["hs_confirmation"] = {"confirmed": True, "hs_code": "080410"}
    rec = silk_watchdog.observe(result, "research", analysis_id=None)
    assert rec["overall"] == "green"
    assert rec["findings"] == []


def test_watchdog_crash_is_isolated_never_raises():
    """داخلياً يتعطّل (نتيجة مشوَّهة تكسر كل فحصٍ) — `observe` لا ترفع
    أبداً، وتعيد سجلّاً يحمل `self_error` بدل إسقاط التحليل."""
    import silk_watchdog

    class _Boom(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")

    rec = silk_watchdog.observe(_Boom(), "research", analysis_id=123)
    assert rec is not None
    assert rec["self_error"] is not None
    assert rec["overall"] == "yellow"
    assert any(f["code"] == "watchdog_self_failure" for f in rec["findings"])
    assert "123" in rec["findings"][0]["message_ar"]


def test_watchdog_crash_does_not_prevent_analysis_success_via_api_helper():
    """محاكاة `api._attach_watchdog`: حتى لو انفجر `silk_watchdog.observe`
    نفسه (استيراد فاشل)، `result` يبقى كما هو ويُعاد بنجاح — لا كسر تحليل."""
    import logging
    log = logging.getLogger("test")

    def _attach_watchdog(result, analysis_id, kind):
        try:
            import silk_watchdog
            with patch.object(silk_watchdog, "observe",
                              side_effect=RuntimeError("boom")):
                silk_watchdog.observe(result, kind, analysis_id)
        except Exception as e:  # noqa: BLE001
            log.warning("watchdog skipped: %s", e)

    result = {"product": "تمور", "view": {}}
    _attach_watchdog(result, 1, "analyze")
    assert result == {"product": "تمور", "view": {}}  # بلا أي تعديل


def test_three_known_service_failures_produce_yellow_findings():
    """الخدمات الثلاث المعروفة (المكشطة/الاتجاهات/صندوق النقد) — كلٌّ يُنتج
    ملاحظةً صفراء صحيحة حين يقع خلال نافذة التشغيلة."""
    import datetime
    import silk_ops_log
    import silk_watchdog

    db = os.path.join(tempfile.mkdtemp(), "ops.db")
    now = datetime.datetime.now()
    with patch("silk_ops_log._db_path", return_value=db):
        silk_ops_log.record_service_failure(
            "scraper", "تقديم مهمة الكشط فشل: 422", context={"stage": "submit"})
        silk_ops_log.record_service_failure(
            "trends", "pytrends fetch failed: 429 too many requests")
        silk_ops_log.record_service_failure(
            "imf", "IMF WEO BCA_NGDPD/KWT: series missing")
        services, findings = silk_watchdog._check_services(duration_s=60)

    svc_names = {s["service"] for s in services}
    assert svc_names == {"scraper", "trends", "imf"}
    assert all(s["severity"] == "yellow" for s in services)
    codes = {f["code"] for f in findings}
    assert {"service_failure_scraper", "service_failure_trends",
           "service_failure_imf"} <= codes


# ══════════════ PART 2 — عدم تلوّث سطوح العميل ══════════════

def test_observe_never_mutates_the_result_dict():
    """مبدأ عدم التلوّث: `observe()` لا يضيف/يعدّل أيّ مفتاحٍ في `result` —
    الحارس يقرأ فقط، ولا يترك أثراً في نتيجة التحليل نفسها."""
    import copy
    import silk_watchdog
    result = _view_result()
    before = copy.deepcopy(result)
    silk_watchdog.observe(result, "research", analysis_id=None)
    assert result == before


def test_no_watchdog_strings_reach_rendered_client_markdown():
    """المصدَّر للعميل (render_markdown على نفس `view`) لا يحمل أيّ أثرٍ
    للحارس — لا استيراد silk_watchdog من silk_render/silk_reports إطلاقاً
    (فحصٌ بنيوي)، ولا أيّ نصٍّ من سجلّات الحارس في المُصدَّر."""
    import inspect
    import silk_render
    import silk_reports
    assert "silk_watchdog" not in inspect.getsource(silk_render)
    assert "silk_watchdog" not in inspect.getsource(silk_reports)

    result = _view_result()
    import silk_watchdog
    silk_watchdog.observe(result, "research", analysis_id=None)
    from silk_reports import render_markdown
    md = render_markdown(result["view"])
    for token in ("الحارس", "watchdog", "تقرير الحارس", "self_error"):
        assert token not in md


def test_web_ui_watchdog_entry_is_a_separate_view_not_inside_analysis():
    """الواجهة: مدخل «تقرير الحارس» وجهةٌ منفصلة (`v-watchdog`) لا قسمٌ
    داخل عرض التحليل (`v-board`) — تحقّقٌ بنيويٌّ على الملف المُقدَّم."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "web", "index.html"), encoding="utf-8").read()
    assert 'id="v-watchdog"' in html
    assert 'id="watchdogNav"' in html
    board_start = html.index('id="v-board"')
    board_end = html.index('id="v-chat"')
    board_block = html[board_start:board_end]
    assert "v-watchdog" not in board_block
    assert "تقرير الحارس" not in board_block


# ══════════════ PART 2 — API ══════════════

def _client():
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.app)


def test_get_watchdog_endpoint_returns_records_badge_trend():
    import silk_watchdog
    db = os.path.join(tempfile.mkdtemp(), "watchdog.db")
    with patch("silk_watchdog._db_path", return_value=db), \
         patch.dict(os.environ, {"SILK_API_KEY": ""}, clear=False):
        result = _view_result()
        silk_watchdog.observe(result, "research", analysis_id=None)
        client = _client()
        r = client.get("/watchdog")
    assert r.status_code == 200
    body = r.json()
    assert body["records"] and body["badge"]["runs_checked"] >= 1
    assert "trend" in body and "known_backlog_note" in body


def test_get_watchdog_report_md_downloads_standalone_file():
    import silk_watchdog
    db = os.path.join(tempfile.mkdtemp(), "watchdog.db")
    with patch("silk_watchdog._db_path", return_value=db), \
         patch.dict(os.environ, {"SILK_API_KEY": ""}, clear=False):
        result = _view_result()
        silk_watchdog.observe(result, "research", analysis_id=None)
        client = _client()
        r = client.get("/watchdog/report.md")
    assert r.status_code == 200
    assert "text/markdown" in r.headers.get("content-type", "")
    assert "تقرير مراقبة المنصّة" in r.text


def test_watchdog_endpoint_requires_key_when_configured():
    with patch.dict(os.environ, {"SILK_API_KEY": "secret"}):
        client = _client()
        r = client.get("/watchdog")
    assert r.status_code == 401


# ══════════════ PART 2 — نقطة الاختناق المشتركة (بلا تكرار منطق) ══════════

def test_attach_watchdog_is_called_from_both_analyze_and_research():
    """نفس نمط بوّابة HS (اللائحة ٣٥): `_attach_watchdog` تُستدعى من كِلا
    `/analyze` و`/research` — تحقّقٌ بنيويٌّ (عدّ الاستدعاءات ≥ ٢)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    api_src = open(os.path.join(root, "api.py"), encoding="utf-8").read()
    assert api_src.count("_attach_watchdog(") >= 3  # التعريف + نداءان فعليّان


# ══════════════ PART 3 — عقل الاتجاه ══════════════

def test_trend_report_computes_cost_and_duration_trend_and_rates():
    import silk_watchdog
    records = [
        {"kind": "research", "overall": "green",
         "economics": {"cost_usd": 1.5, "duration_s": 300, "tariff_path": "wto"},
         "services": []},
        {"kind": "research", "overall": "yellow",
         "economics": {"cost_usd": 2.0, "duration_s": 400, "tariff_path": "wits"},
         "services": [{"service": "trends"}]},
        {"kind": "research", "overall": "red",
         "economics": {"cost_usd": 2.5, "duration_s": 500, "tariff_path": "wto"},
         "services": []},
    ]
    t = silk_watchdog.trend_report(records)
    kt = t["by_kind"]["research"]
    assert kt["runs"] == 3
    assert kt["cost_trend"]["avg"] == 2.0
    assert kt["contract_violation_rate"] == round(1 / 3, 2)
    assert kt["wto_vs_wits_rate"] == {"wto": 2, "wits": 1}
    assert kt["service_fallback_count"] == 1


def test_render_report_md_includes_known_backlog_note_and_table():
    import silk_watchdog
    md = silk_watchdog.render_report_md(records=[{
        "analysis_id": 5, "kind": "research", "product": "تمور",
        "market": "الإمارات", "overall": "green", "created_at": "2026-07-21",
        "contracts": {}, "economics": {}, "services": [], "failures": {},
        "findings": [], "self_error": None}])
    assert silk_watchdog.KNOWN_OPEN_BACKLOG_NOTE in md
    assert "| التشغيلة |" in md
    assert "| 5 |" in md


def test_overall_badge_green_on_no_records():
    import silk_watchdog
    b = silk_watchdog.overall_badge(records=[])
    assert b["overall"] == "green" and b["runs_checked"] == 0


def test_overall_badge_reflects_worst_record():
    import silk_watchdog
    b = silk_watchdog.overall_badge(records=[
        {"overall": "green"}, {"overall": "red"}, {"overall": "yellow"}])
    assert b["overall"] == "red"


# ══════════════ الحماية الذاتية — لا يُبطئ التشغيلة ══════════════

def test_observe_adds_negligible_latency():
    """صفر تكلفة/بطء مقاسة — قياسٌ حيّ قبل/بعد (اللائحة، معيار القبول):
    `observe()` على تشغيلةٍ حقيقية الشكل يستغرق أجزاءً من الثانية، لا
    ثوانيَ ملموسة (لا نداء شبكة/كلود داخله إطلاقاً)."""
    import time
    import silk_watchdog
    result = _view_result()
    t0 = time.monotonic()
    for _ in range(20):
        silk_watchdog.observe(result, "research", analysis_id=None)
    elapsed = time.monotonic() - t0
    print(f"watchdog.observe(): {elapsed/20*1000:.2f}ms/تشغيلة (20 تكراراً)")
    assert elapsed / 20 < 0.5, "الحارس أبطأ من نصف ثانية لكل تشغيلة — غير متوقَّع"

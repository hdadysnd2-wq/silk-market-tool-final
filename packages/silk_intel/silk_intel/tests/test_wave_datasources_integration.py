"""أقفال دمج المصادر الجديدة (الموجة: دمج ستة مواقع) — كل مصدر جديد يتبع نفس
العقود: فجوة معلنة عند الفشل (لا اختلاق)، إعلان للمشغّل عبر ops log، انحياز بحث
لا كشط، واستشهاد. اختبارات هرمتية تماماً (لا شبكة): الأشكال الحيّة تُحقَن كلقطات
مرجعية مثبتة، والفشل يُحاكى بإرجاع None من طبقة التخزين المؤقت.

Run: python3 -m pytest tests/test_wave_datasources_integration.py -q
"""
import datetime
import os
from contextlib import contextmanager
from unittest.mock import patch

import silk_imf_agent as imf
import silk_wto_tariff as wto
import silk_tariffs_agent as tar
import silk_missions as M
import silk_llm_runtime as RT
import silk_websearch_agent as WS
from silk_data_layer import DataPoint, public_source_url, WORLD_BANK_AR_PORTAL


@contextmanager
def _ops_db(tmp_path):
    """وجّه سجل العمليات لملف مؤقت + أعِد ضبطه — قراءة نظيفة لكل اختبار."""
    p = str(tmp_path / "ops.db")
    old = os.environ.get("SILK_OPS_LOG_DB")
    os.environ["SILK_OPS_LOG_DB"] = p
    try:
        yield p
    finally:
        if old is None:
            os.environ.pop("SILK_OPS_LOG_DB", None)
        else:
            os.environ["SILK_OPS_LOG_DB"] = old


# ── IMF WEO ────────────────────────────────────────────────────────────────
# لقطة مرجعية من واجهة IMF DataMapper العامة (الشكل الرسمي):
_IMF_SHAPE = {"values": {"NGDP_RPCH": {"NLD": {
    "2021": 6.24, "2022": 4.35, "2023": 0.06, "2027": 1.4}}}}


def test_imf_shape_lock_parses_recorded_response():
    """قفل الشكل: يُستخرَج الرقم من لقطة DataMapper الحقيقية الشكل، وأحدث سنة
    غير مستقبلية تُختار (2023 لا 2027 التنبؤية)، بمصدر وسنة موسومَين."""
    with patch("silk_cache.cached_get", return_value=_IMF_SHAPE):
        dp = imf.imf_indicator("NLD", "gdp_growth")
    assert dp.value == 0.06
    assert dp.source == "IMF WEO"
    assert "2023" in dp.note and "IMF" in dp.note
    # سنة صريحة مطلوبة تُحترَم:
    with patch("silk_cache.cached_get", return_value=_IMF_SHAPE):
        assert imf.imf_indicator("NLD", "gdp_growth", 2022).value == 4.35


def test_imf_declared_gap_on_fetch_failure_and_ops_logged(tmp_path):
    """لا اختلاق: فشل الجلب => None/0.0 + سطر service_failure للمشغّل."""
    with _ops_db(tmp_path):
        import silk_ops_log
        with patch("silk_cache.cached_get", return_value=None):
            dp = imf.imf_indicator("NLD", "inflation")
        assert dp.value is None and dp.confidence == 0.0
        assert dp.status == "fetch_failed"
        errs = silk_ops_log.last_errors(10)
        assert any(e["kind"] == "service_failure"
                   and "imf" in (e.get("context") or {}).get("service", "")
                   for e in errs)


def test_imf_bad_metric_and_iso_are_declared_gaps():
    dp1 = imf.imf_indicator("NLD", "not_a_metric")
    dp2 = imf.imf_indicator("XX", "gdp_growth")
    assert dp1.value is None and dp2.value is None


def test_imf_no_record_is_distinct_from_fetch_failure():
    """ردّ ناجح بلا سلسلة للبلد => no_record (لا fetch_failed) — لا اختلاق."""
    with patch("silk_cache.cached_get",
               return_value={"values": {"NGDP_RPCH": {}}}):
        dp = imf.imf_indicator("NLD", "gdp_growth")
    assert dp.value is None and dp.status == "no_record"


def test_imf_forecast_year_is_flagged_and_lower_confidence():
    """#3 (صدق المصدر): قيمة سنة مستقبلية/حالية = تقدير WEO — تُوسَم وتُخفَّض
    ثقتها (0.6 لا 0.85) فلا تُقدَّم بيقين الأرقام المُحقَّقة."""
    future = str(datetime.date.today().year + 2)
    shape = {"values": {"NGDP_RPCH": {"NLD": {future: 2.0}}}}
    with patch("silk_cache.cached_get", return_value=shape):
        dp = imf.imf_indicator("NLD", "gdp_growth")
    assert dp.value == 2.0 and dp.confidence == 0.6 and "تقدير" in dp.note


def test_imf_requested_year_unavailable_is_declared_not_silent():
    """#4: سنة مطلوبة غير متاحة => أحدث متاح مع ملاحظة صريحة، لا تمرير صامت."""
    shape = {"values": {"NGDP_RPCH": {"NLD": {"2015": 1.0}}}}
    with patch("silk_cache.cached_get", return_value=shape):
        dp = imf.imf_indicator("NLD", "gdp_growth", 2010)
    assert dp.value == 1.0 and "غير متاحة" in dp.note and "2010" in dp.note


def test_imf_reaches_risk_and_macro_via_tool_not_forced_network():
    """IMF يصل المخاطر/الكلي عبر أداة imf_indicator + تعليمات البعثة — لا إلحاق
    شبكة حتمي في المسار الحار (انسجام مع حساسية التكلفة/السرعة D-06)."""
    assert "imf_indicator" in M.MISSIONS["risk_news"]["allowed_tools"]
    assert "imf_indicator" in M.MISSIONS["demographics_economy"]["allowed_tools"]
    # لا إلحاق حتمي غير مشروط في run_all_missions (لا نداء شبكة إضافي/تشغيلة).
    import inspect
    assert "_augment_risk_news_imf" not in inspect.getsource(M.run_all_missions)
    assert "imf_indicator" in M.MISSIONS["risk_news"]["instructions"]


# ── WTO TTD ────────────────────────────────────────────────────────────────
# لقطة مرجعية من واجهة WTO Timeseries (الشكل الرسمي):
_WTO_SHAPE = {"Dataset": [
    {"Value": 8.0, "Year": 2021, "ProductOrSectorCode": "080410",
     "ReportingEconomyCode": "918", "Unit": "Percent"}]}


def test_wto_shape_lock_parses_recorded_response():
    with patch.dict(os.environ, {"WTO_TTD_API_KEY": "k"}):
        with patch("silk_cache.cached_get", return_value=_WTO_SHAPE):
            dp = wto.wto_applied_tariff("080410", "NLD", "SAU", 2021)
    assert dp.value == 8.0
    assert dp.source == "WTO TTD"
    assert "080410" in dp.note and "الاتحاد الأوروبي" in dp.note  # EU→918


def test_wto_no_key_is_declared_gap_with_zero_network_calls():
    """بلا مفتاح => فجوة معلنة فوراً بلا أي نداء شبكة (لا اختلاق مفتاح)."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("WTO_TTD_API_KEY", None)
        os.environ.pop("WTO_API_KEY", None)
        with patch("silk_cache.cached_get") as cg:
            dp = wto.wto_applied_tariff("080410", "NLD")
        cg.assert_not_called()
    assert dp.value is None and "غير مُهيَّأ" in dp.note


def test_wto_key_sent_as_header_not_url_param():
    """#5 (نظافة الأسرار): المفتاح في ترويسة Ocp-Apim-Subscription-Key لا في
    استعلام الـURL — فلا يظهر السرّ في الرابط (تسرّب للوسطاء/البروكسي)."""
    captured = {}

    def fake_cached_get(url, params=None, ttl_seconds=0, fetcher=None,
                        headers=None):
        captured["params"] = params or {}
        captured["headers"] = headers or {}
        return _WTO_SHAPE

    with patch.dict(os.environ, {"WTO_TTD_API_KEY": "secret-k"}):
        with patch("silk_cache.cached_get", side_effect=fake_cached_get):
            dp = wto.wto_applied_tariff("080410", "NLD", "SAU", 2021)
    assert dp.value == 8.0
    assert "subscription-key" not in captured["params"]
    assert "secret-k" not in str(captured["params"])  # السرّ ليس في الاستعلام
    assert captured["headers"].get("Ocp-Apim-Subscription-Key") == "secret-k"


def test_wto_fetch_failure_declared_gap_and_ops_logged(tmp_path):
    with _ops_db(tmp_path):
        import silk_ops_log
        with patch.dict(os.environ, {"WTO_TTD_API_KEY": "k"}):
            with patch("silk_cache.cached_get", return_value=None):
                dp = wto.wto_applied_tariff("080410", "NLD")
        assert dp.value is None and dp.status == "fetch_failed"
        errs = silk_ops_log.last_errors(10)
        assert any((e.get("context") or {}).get("service") == "wto_ttd"
                   for e in errs)


# ── سلسلة التراجع للتعريفة: WTO → WITS → فجوة معلنة ─────────────────────────
def test_tariff_fallback_prefers_wto_when_available():
    served = DataPoint(8.0, "WTO TTD", 0.9, "wto")
    with patch("silk_wto_tariff.wto_applied_tariff", return_value=served), \
         patch("silk_tariffs_agent.applied_tariff") as wits:
        dp = tar.tariff_with_fallback("080410", "NLD")
    assert dp.source == "WTO TTD" and dp.value == 8.0
    wits.assert_not_called()  # WTO خدم — لا نداء WITS


def test_tariff_fallback_falls_back_to_wits_when_wto_gap():
    wto_gap = DataPoint(None, "WTO TTD", 0.0, "no key")
    wits_ok = DataPoint(5.0, "World Bank WITS", 0.9, "wits served")
    with patch("silk_wto_tariff.wto_applied_tariff", return_value=wto_gap), \
         patch("silk_tariffs_agent.applied_tariff", return_value=wits_ok):
        dp = tar.tariff_with_fallback("080410", "NLD")
    assert dp.source == "World Bank WITS" and dp.value == 5.0


def test_tariff_fallback_both_gap_is_declared_gap_naming_both():
    wto_gap = DataPoint(None, "WTO TTD", 0.0, "wto down")
    wits_gap = DataPoint(None, "World Bank WITS", 0.0, "wits down")
    with patch("silk_wto_tariff.wto_applied_tariff", return_value=wto_gap), \
         patch("silk_tariffs_agent.applied_tariff", return_value=wits_gap):
        dp = tar.tariff_with_fallback("080410", "NLD")
    assert dp.value is None
    assert dp.source == "World Bank WITS"  # استقرار للاختبارات القائمة
    assert "WTO TTD" in dp.note and "wits down" in dp.note


# ── Wave 2: انحياز النطاقات المُفضَّلة (بلا كشط) ────────────────────────────
def _dp_result(title, link):
    return DataPoint({"title": title, "snippet": "s", "link": link},
                     "Web Search (Serper)", 0.5, "organic", "2026-07-20")


def test_preferred_domains_ranked_first_and_tagged_secondary():
    base = [_dp_result("general", "https://example.com/a")]
    pref = [_dp_result("culture", "https://globalbusinessculture.com/nl")]

    def fake_search(q, num=5, gl=None, hl=None):
        return pref if "site:globalbusinessculture.com" in q else base

    with patch("silk_websearch_agent.web_search", side_effect=fake_search):
        out = WS.web_search_prioritized(
            "dutch food culture", preferred_domains=["globalbusinessculture.com"])
    assert out[0].value["link"] == "https://globalbusinessculture.com/nl"
    assert "◐" in out[0].note and out[0].confidence == 0.4
    assert "globalbusinessculture.com" in out[0].source
    # النتيجة العامة تبقى بعدها (لا حذف)
    assert any(d.value["link"] == "https://example.com/a" for d in out)


def test_preferred_domains_empty_is_identical_to_web_search():
    base = [_dp_result("g", "https://x.com/a")]
    with patch("silk_websearch_agent.web_search", return_value=base) as ws:
        out = WS.web_search_prioritized("q", preferred_domains=[])
    assert out == base
    ws.assert_called_once()  # لا استعلامات site: إضافية


def test_preferred_domains_ignores_mismatched_host():
    """نتيجة لا يطابق مضيفها الفعليّ النطاق المُفضَّل تُهمَل (لا تُوسَم زوراً)."""
    base = [_dp_result("g", "https://x.com/a")]
    wrong = [_dp_result("spoof", "https://evil.com/globalbusinessculture.com")]

    def fake(q, num=5, gl=None, hl=None):
        return wrong if "site:" in q else base

    with patch("silk_websearch_agent.web_search", side_effect=fake):
        out = WS.web_search_prioritized(
            "q", preferred_domains=["globalbusinessculture.com"])
    assert all("evil.com" not in (d.value or {}).get("link", "") for d in out)


def test_preferred_domains_reject_suffix_spoofed_host():
    """#2: مضيف يتضمّن النطاق كسابقة (ccacoalition.org.evil.com) يُرفَض؛ نطاق
    فرعيّ حقيقيّ (blog.ccacoalition.org) يُقبَل."""
    base = [_dp_result("g", "https://x.com/a")]
    spoof = [_dp_result("spoof", "https://ccacoalition.org.evil.com/p")]

    def fake_spoof(q, num=5, gl=None, hl=None):
        return spoof if "site:" in q else base

    with patch("silk_websearch_agent.web_search", side_effect=fake_spoof):
        out = WS.web_search_prioritized("q", preferred_domains=["ccacoalition.org"])
    assert all("evil.com" not in (d.value or {}).get("link", "") for d in out)

    sub = [_dp_result("ok", "https://blog.ccacoalition.org/p")]

    def fake_sub(q, num=5, gl=None, hl=None):
        return sub if "site:" in q else base

    with patch("silk_websearch_agent.web_search", side_effect=fake_sub):
        out = WS.web_search_prioritized("q", preferred_domains=["ccacoalition.org"])
    assert any("blog.ccacoalition.org" in (d.value or {}).get("link", "")
               for d in out)


def test_web_search_counts_each_serper_post_in_data_economics():
    """#1 (لا إنفاق خفيّ، عائلة الدرسين ١٦/٢٦): كل نداء Serper فعليّ يُحسَب
    live_fetches في عدّاد اقتصاد البيانات."""
    import silk_context
    c = silk_context.begin_data_counter()
    with patch.dict(os.environ, {"SEARCH_API_KEY": "k"}):
        with patch("requests.post", side_effect=OSError("blocked")):
            WS.web_search("q")
    assert c["live_fetches"] >= 1


def test_preferred_domains_subqueries_are_capped():
    """#1: عدد استعلامات site: الفرعية مسقوف (لا مُضاعِف غير محدود)."""
    site_calls = []

    def fake(q, num=5, gl=None, hl=None):
        if "site:" in q:
            site_calls.append(q)
            return [_dp_result("r", "https://a.com/x")]
        return [_dp_result("b", "https://x.com/a")]

    with patch("silk_websearch_agent.web_search", side_effect=fake):
        WS.web_search_prioritized(
            "q", preferred_domains=["d1.com", "d2.com", "d3.com", "d4.com"])
    assert len(site_calls) <= WS._MAX_PREFERRED_SUBQUERIES


def test_preferred_domains_map_keys_all_have_web_search_tool():
    """كل مفتاح في PREFERRED_DOMAINS بعثة حقيقية تملك web_search — لا إعداد ميت."""
    for key in M.PREFERRED_DOMAINS:
        assert key in M.MISSIONS, f"{key} ليس بعثة"
        assert "web_search" in M.MISSIONS[key]["allowed_tools"], \
            f"{key} بلا web_search — انحياز ميت"


def test_owner_domains_are_wired_to_the_right_missions():
    assert "globalbusinessculture.com" in M.PREFERRED_DOMAINS["consumer_culture"]
    assert "ccacoalition.org" in M.PREFERRED_DOMAINS["customs_requirements"]
    assert "tradingeconomics.com" in M.PREFERRED_DOMAINS["risk_news"]


# ── تسجيل الأدوات + وصل البعثات ─────────────────────────────────────────────
def test_imf_tool_registered_and_wired_to_risk_and_macro():
    assert "imf_indicator" in RT.TOOLS
    assert "imf_indicator" in M.MISSIONS["risk_news"]["allowed_tools"]
    assert "imf_indicator" in M.MISSIONS["demographics_economy"]["allowed_tools"]


# ── Wave 3: البوّابة العربية للبنك الدولي (استشهاد العميل فقط) ──────────────
def test_world_bank_arabic_portal_only_for_client_citation():
    assert public_source_url("World Bank", arabic=True) == WORLD_BANK_AR_PORTAL
    assert public_source_url("World Bank (لقطة)", arabic=True) == WORLD_BANK_AR_PORTAL
    # الافتراضي/التشغيلي بلا تغيير:
    assert public_source_url("World Bank") == "https://data.worldbank.org/"
    # مصدر آخر لا يتأثر بالعلَم العربي:
    assert public_source_url("UN Comtrade", arabic=True) == \
        "https://comtradeplus.un.org/"


# ── انضباط الشروط/حقوق النشر: لا كشط في أي وحدة مصدر جديدة ──────────────────
def test_new_source_modules_do_no_html_scraping():
    """المصادر الجديدة تستعمل واجهات JSON رسمية فقط — لا مكتبة استخلاص HTML."""
    import inspect
    for mod in (imf, wto):
        src = inspect.getsource(mod)
        for banned in ("BeautifulSoup", "bs4", "lxml.html", "readability",
                       ".find_all(", "html.parser"):
            assert banned not in src, f"{mod.__name__} يكشط؟ {banned}"

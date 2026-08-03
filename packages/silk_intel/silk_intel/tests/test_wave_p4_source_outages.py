"""اختبارات بلاغ حي رابع (سجل إنتاج، تشغيلة تمور/هولندا الثالثة): خمسة
أعطال مصادر مرصودة في سجل Railway الفعلي:

1. WITS 400 "WITSAPIError/Invalid_Reporter" — الطلب كان يرسل ISO3 الأبجدي
   ("NLD") بينما واجهة WITS SDMX تتوقع رموزاً رقمية، وdatatype كان "AHS"
   (غير صالح — reported/aveestimated فقط)، وعضو الاتحاد الأوروبي يجب أن
   يُستعلم برمز الاتحاد (918) لأن تعريفته موحّدة على مستوى الاتحاد.
2. WGI (PV.EST/RL.EST/RQ.EST) مؤرشفة في قاعدة WDI الافتراضية — موطنها
   الحالي source=3 (قاعدة WGI المستقلة)؛ يُمرَّر صراحة.
3. كومتريد 429 متكرر — تراجُع أسّي بتشويش عشوائي (jitter) + نافذة تباعد
   أوسع خاصة بكومتريد (SILK_COMTRADE_MIN_GAP_MS) بين النداءات المتوازية.
4. FAOSTAT 401 — قاطع دارة تلقائي بعد أول 401/403 + مفتاح تعطيل صريح
   (SILK_DISABLE_FAOSTAT) — فجوة معلنة نظيفة بدل محاولة فاشلة كل تشغيلة.
5. فشل الكاتب/ai_report يُسجَّل بسطر ERROR واضح (نوع الاستثناء + المرحلة)
   غير مشروط بالتتبّع — يظهر في سجلات Railway؛ ورد HTTP ناجح بلا نص
   (المسار الصامت الوحيد سابقاً) صار يلتقط empty_response في last_error.

لا شبكة ولا مفتاح حقيقي مطلوبان (نفس تقليد المستودع الهيرمتي).
Run:  python3 -m pytest tests/test_wave_p4_source_outages.py -q
"""
import contextlib
import logging
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


# ── ١: WITS — رموز رقمية، الاتحاد الأوروبي 918، datatype=reported ─────────

def _wits_capture():
    """صائد URL لنداء WITS الواحد — يعيد (القاموس الملتقط، الرد المزيّف)."""
    captured = {}

    def _fake_get(url, params=None, timeout=None):
        captured["url"] = url
        r = MagicMock()
        r.raise_for_status = lambda: None
        r.json = lambda: {"dataSets": [{"series": {
            "0": {"observations": {"0": [4.5]}}}}]}
        r.text = ""
        return r

    return captured, _fake_get


def test_wits_url_uses_numeric_codes_not_iso3_alpha():
    from silk_tariffs_agent import applied_tariff

    captured, fake_get = _wits_capture()
    with patch("silk_tariffs_agent.requests.get", side_effect=fake_get):
        dp = applied_tariff("080410", "CHN", "SAU", 2022)

    url = captured["url"]
    assert "/reporter/156/" in url          # الصين = 156 رقمياً
    assert "/partner/682/" in url           # السعودية = 682 رقمياً
    assert "CHN" not in url and "SAU" not in url  # لا أبجدي في المسار
    assert dp.value == 4.5


def test_wits_eu_member_maps_to_eu_reporter_918():
    """بلاغ حي: هولندا (528) لا تُبلِّغ تعريفة خاصة — تعريفة الاتحاد
    الأوروبي الموحّدة تحت المُبلِّغ 918؛ هذا أصل فجوة التعريفة المزمنة."""
    from silk_tariffs_agent import applied_tariff

    captured, fake_get = _wits_capture()
    with patch("silk_tariffs_agent.requests.get", side_effect=fake_get):
        dp = applied_tariff("080410", "NLD", "SAU", 2022)

    assert "/reporter/918/" in captured["url"]
    assert "NLD" not in captured["url"]
    assert "الاتحاد الأوروبي" in dp.note   # المصدر الفعلي معلن في الملاحظة


def test_wits_datatype_is_reported_not_ahs():
    from silk_tariffs_agent import applied_tariff

    captured, fake_get = _wits_capture()
    with patch("silk_tariffs_agent.requests.get", side_effect=fake_get):
        applied_tariff("080410", "CHN", "SAU", 2022)

    assert "/datatype/reported" in captured["url"]
    assert "AHS" not in captured["url"]


def test_wits_unknown_market_declares_gap_without_any_http():
    from silk_tariffs_agent import applied_tariff

    with patch("silk_tariffs_agent.requests.get") as g:
        dp = applied_tariff("080410", "XXX", "SAU", 2022)

    g.assert_not_called()
    assert dp.value is None
    assert "فجوة معلنة" in dp.note


def test_wits_reporter_code_helper_pads_to_three_digits():
    from silk_tariffs_agent import _wits_reporter_code

    code, is_eu = _wits_reporter_code("BHR")   # البحرين m49 = 048
    assert code == "048" and is_eu is False
    code, is_eu = _wits_reporter_code("DEU")   # عضو اتحاد أوروبي
    assert code == "918" and is_eu is True


# ── ٢: WGI — source=3 صراحة ────────────────────────────────────────────────

def _wb_capture(records):
    captured = {}

    def _fake_http_get(url, params=None):
        captured["url"] = url
        captured["params"] = dict(params or {})
        r = MagicMock()
        r.raise_for_status = lambda: None
        r.json = lambda: [{"page": 1}, records]
        return r

    return captured, _fake_http_get


def test_world_bank_wgi_indicator_passes_source_3():
    import silk_data_layer as dl

    captured, fake = _wb_capture([{"value": -0.2, "date": "2023"}])
    with patch.object(dl, "_cached_get", return_value=None), \
         patch.object(dl, "_http_get", side_effect=fake):
        dp = dl.world_bank("NLD", "PV.EST")

    assert captured["params"].get("source") == "3"
    assert dp.value == -0.2


def test_world_bank_all_three_governance_codes_mapped_to_source_3():
    from silk_data_layer import _WB_INDICATOR_SOURCE

    for code in ("PV.EST", "RL.EST", "RQ.EST"):
        assert _WB_INDICATOR_SOURCE[code] == "3"


def test_every_mission_governance_indicator_is_source3_registered():
    """LESSONS.md البند ٧ (حارس تناسق عبر-وحدات): كل مؤشر حوكمة (WGI، ينتهي
    بـ`.EST`) تعرضه أداة worldbank_indicator للبعثات
    (silk_llm_runtime._WB_INDICATORS) يجب أن يكون مسجَّلاً في خريطة المصدر
    (silk_data_layer._WB_INDICATOR_SOURCE) بقيمة "3" — وإلا يسقط الطلب إلى
    المصدر الأرشيفي الافتراضي (source=2) فيعيد صفحة فارغة بصمت: بالضبط
    الفشل الذي يوجد هذا الدرس لمنعه. إضافة مؤشر .EST جديد للبعثات بلا تسجيله
    هنا تُفشِل الاختبار فوراً بدل أن تتسرّب فجوة صامتة."""
    from silk_llm_runtime import _WB_INDICATORS
    from silk_data_layer import _WB_INDICATOR_SOURCE

    governance = {code for code in _WB_INDICATORS.values()
                  if code.endswith(".EST")}
    assert governance, "لا مؤشر حوكمة معروض للبعثات — تغيّرت البنية؟"
    for code in governance:
        assert _WB_INDICATOR_SOURCE.get(code) == "3", (
            f"مؤشر الحوكمة {code} معروض للبعثات لكنه غير مسجَّل في "
            f"_WB_INDICATOR_SOURCE بـsource=3 — سيسقط لمصدر أرشيفي فارغ بصمت")


def test_world_bank_non_wgi_indicator_keeps_default_source():
    """حارس انحدار: مؤشر WDI عادي (سكان) بلا معامل source — القاعدة
    الافتراضية تخدمه أصلاً."""
    import silk_data_layer as dl

    captured, fake = _wb_capture([{"value": 17000000, "date": "2023"}])
    with patch.object(dl, "_cached_get", return_value=None), \
         patch.object(dl, "_http_get", side_effect=fake):
        dl.world_bank("NLD", "SP.POP.TOTL")

    assert "source" not in captured["params"]


# ── ٣: كومتريد — jitter + نافذة تباعد خاصة ────────────────────────────────

def test_backoff_delay_is_exponential_with_bounded_jitter():
    from silk_data_layer import _backoff_delay

    for attempt in range(4):
        base = 1.0 * (2 ** attempt)
        for _ in range(20):
            d = _backoff_delay(attempt)
            assert base <= d <= min(2 * base, 30.0), f"attempt {attempt}: {d}"


def test_backoff_delay_jitter_actually_varies():
    """بلاغ حي: مهلة حتمية تجعل النداءات الفاشلة معاً تعيد المحاولة معاً —
    التشويش يجب أن يُنتج قيماً مختلفة فعلاً."""
    from silk_data_layer import _backoff_delay

    values = {_backoff_delay(2) for _ in range(30)}
    assert len(values) > 1


def test_backoff_delay_respects_retry_after_with_small_jitter():
    from silk_data_layer import _backoff_delay

    for _ in range(20):
        d = _backoff_delay(0, retry_after="7")
        assert 7.0 <= d <= 7.5


def test_comtrade_host_gets_wider_min_gap_than_generic_hosts():
    from silk_data_layer import _min_gap_ms

    with _env(SILK_COMTRADE_MIN_GAP_MS=None, SILK_HTTP_MIN_GAP_MS=None):
        assert _min_gap_ms("comtradeapi.un.org") == 1100.0
        assert _min_gap_ms("api.worldbank.org") == 250.0


def test_comtrade_min_gap_env_overridable():
    from silk_data_layer import _min_gap_ms

    with _env(SILK_COMTRADE_MIN_GAP_MS="2000"):
        assert _min_gap_ms("comtradeapi.un.org") == 2000.0


# ── ٤: FAOSTAT — قاطع دارة + مفتاح تعطيل ──────────────────────────────────

def test_faostat_kill_switch_declares_gap_with_zero_http():
    import silk_faostat_agent as fa

    fa.reset_auth_block()
    with _env(SILK_DISABLE_FAOSTAT="1"), \
         patch("silk_faostat_agent.requests.get") as g:
        dp = fa.per_capita_supply("NLD", "Dates", 2022)

    g.assert_not_called()
    assert dp.value is None
    assert "SILK_DISABLE_FAOSTAT" in dp.note


def test_faostat_first_401_trips_circuit_breaker_for_the_process():
    import silk_faostat_agent as fa

    fa.reset_auth_block()
    calls = {"n": 0}

    def _fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        r = MagicMock()
        r.status_code = 401
        return r

    try:
        with _env(SILK_DISABLE_FAOSTAT=None), \
             patch("silk_faostat_agent.requests.get", side_effect=_fake_get):
            dp1 = fa.per_capita_supply("NLD", "Dates", 2022)
            dp2 = fa.per_capita_supply("SAU", "Dates", 2022)
    finally:
        fa.reset_auth_block()

    assert calls["n"] == 1                    # النداء الثاني لم يلمس الشبكة
    assert dp1.value is None and dp2.value is None
    assert "401" in dp1.note
    assert "عُطّل تلقائياً" in dp2.note        # فجوة معلنة نظيفة، لا محاولة


def test_faostat_normal_failure_does_not_trip_breaker():
    """حارس: فشل شبكة عادي (لا 401/403) لا يعطّل المصدر — الحجب خاص
    بالمصادقة حصراً."""
    import silk_faostat_agent as fa

    fa.reset_auth_block()
    calls = {"n": 0}

    def _fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        raise OSError("network down")

    try:
        with _env(SILK_DISABLE_FAOSTAT=None), \
             patch("silk_faostat_agent.requests.get", side_effect=_fake_get):
            fa.per_capita_supply("NLD", "Dates", 2022)
            fa.per_capita_supply("SAU", "Dates", 2022)
    finally:
        fa.reset_auth_block()

    assert calls["n"] == 2                    # كلا النداءين حاول فعلاً


# ── ٥: سطر سجل واضح لفشل الكاتب/ai_report ─────────────────────────────────

def test_traced_call_failure_logs_error_line_without_trace_id(caplog):
    """بلاغ حي: سجل Railway لم يحمل أي أثر لفشل الكاتب — التسجيل كان
    مربوطاً بوجود trace_id. الآن سطر ERROR غير مشروط، greppable."""
    import silk_ai_judge as aj

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_ai_judge._call", return_value=None), \
         patch("silk_llm_provider.last_error",
               return_value={"type": "ReadTimeout",
                            "message": "Read timed out. (read timeout=300)"}), \
         caplog.at_level(logging.ERROR, logger="silk_ai_judge"):
        aj.deep_report({}, "خلاصة", {"verdict": "WATCH"}, "تمور", "هولندا")

    line = " ".join(r.getMessage() for r in caplog.records)
    assert "report_call_failed" in line
    assert "stage=draft" in line
    assert "ReadTimeout" in line


def test_ai_report_failure_logs_error_with_analyze_stage(caplog):
    import silk_ai_judge as aj

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_ai_judge._call", return_value=None), \
         patch("silk_llm_provider.last_error",
               return_value={"type": "ConnectTimeout", "message": "x"}), \
         caplog.at_level(logging.ERROR, logger="silk_ai_judge"):
        out = aj.ai_report({"product": "تمور", "hs_code": "080410",
                           "markets": []})

    assert out is None
    line = " ".join(r.getMessage() for r in caplog.records)
    assert "report_call_failed" in line
    assert "stage=analyze_report" in line
    assert "ConnectTimeout" in line


def test_traced_call_success_logs_nothing_at_error_level(caplog):
    import silk_ai_judge as aj

    draft = "\n".join(f"## {i}. {s}\nنص." for i, s in
                      enumerate(aj._REPORT_SECTIONS, 1))
    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("silk_ai_judge._call", return_value=draft), \
         caplog.at_level(logging.ERROR, logger="silk_ai_judge"):
        aj.deep_report({}, "خلاصة", {"verdict": "WATCH"}, "تمور", "هولندا")

    assert not caplog.records


def test_provider_empty_text_response_sets_empty_response_last_error():
    """المسار الصامت الوحيد سابقاً: HTTP 200 بلا كتل نصية كان يعيد None
    بلا سجل ولا last_error — يطابق "السجل لا يحتوي أي أثر" حرفياً."""
    import silk_llm_provider as lp

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "max_tokens", "content": []}

    with _env(ANTHROPIC_API_KEY="test-key"), \
         patch("requests.post", return_value=_Resp()):
        out = lp.AnthropicProvider().complete("sys", "user", 100, "m", 300)

    assert out is None
    err = lp.last_error()
    assert err["type"] == "empty_response"
    assert "max_tokens" in err["message"]

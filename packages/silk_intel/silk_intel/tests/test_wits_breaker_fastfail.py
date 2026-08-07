"""قاطع الدائرة على مسار WITS — fast-fail parity for the tariffs agent (WS4).

`applied_tariff` كان ينادي `requests.get` خاماً متجاوزاً قاطعَ الدائرة
المشترك، فمضيفُ WITS الميت كلّف المهلةَ كاملةً (30s) × كلّ سوقٍ في توسيع
المرحلة الثانية — أرضية صامتة ~10 دقائق. الآن: قاطعٌ مفتوح ⇒ فجوة معلنة
بلا أيّ نداء؛ 4xx (ردّ صحيّ = فجوة بيانات) يسجَّل نجاحاً؛ الأعطال الشبكية
تسجَّل فشلاً فتفتح القاطع بعد العتبة.

هرمتي: الشبكة مقطوعة عبر patch على requests.get (نمط الملف الشقيق
test_tariff_gcc_documented_fallback).
"""

from unittest.mock import patch

import silk_circuit
import silk_tariffs_agent as T

_WITS_HOST = T._WITS_BASE.split("/")[2]


def setup_function(_fn):
    silk_circuit.http_breaker.reset()


def teardown_function(_fn):
    silk_circuit.http_breaker.reset()


def test_open_breaker_fast_fails_without_any_network_call():
    for _ in range(silk_circuit.http_breaker.threshold):
        silk_circuit.http_breaker.record_failure(_WITS_HOST)
    assert silk_circuit.http_breaker.is_open(_WITS_HOST)

    def _must_not_be_called(*a, **k):
        raise AssertionError("requests.get must not be reached while the breaker is open")

    with patch("requests.get", side_effect=_must_not_be_called):
        dp = T.applied_tariff("200811", "FRA", "SAU")
    assert dp.value is None and dp.confidence == 0.0
    assert "قاطع الدائرة" in dp.note


def test_network_failures_open_the_breaker():
    with patch("requests.get", side_effect=OSError("network blocked in test")):
        for _ in range(silk_circuit.http_breaker.threshold):
            dp = T.applied_tariff("200811", "FRA", "SAU")
            assert dp.value is None  # فجوة معلنة، لا استثناء
    assert silk_circuit.http_breaker.is_open(_WITS_HOST)


def test_4xx_is_a_data_gap_not_an_outage():
    class _Resp:
        status_code = 400

        def raise_for_status(self):
            import requests

            err = requests.exceptions.HTTPError(response=self)
            raise err

    with patch("requests.get", return_value=_Resp()):
        for _ in range(silk_circuit.http_breaker.threshold + 1):
            dp = T.applied_tariff("200811", "FRA", "SAU")
            assert dp.value is None
            assert "ليس عطلاً تقنياً" in dp.note
    # المضيف أجاب — القاطع يبقى مغلقاً مهما تكرّرت فجوات البيانات.
    assert not silk_circuit.http_breaker.is_open(_WITS_HOST)

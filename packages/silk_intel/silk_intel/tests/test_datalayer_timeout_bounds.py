"""حدودُ الزمن على مسار المزوّد — engine data-layer time bounds (تدقيق C15/C16).

C16: مهلةُ نقلٍ (Timeout/ConnectionError) يجب أن تُسجَّل فشلاً في قاطع الدائرة
فيفتح بعد العتبة ويوقف أرضيةَ المهلة الكاملة × كلّ سوق. C15: مهلةُ عامل Celery
(SoftTimeLimitExceeded) يجب أن تصعد من المعالِجات العريضة لا أن تُبتلَع كفجوة.
هرمتي: الشبكة مقطوعة، والاستثناءات محقونة.
"""

from unittest.mock import patch

import requests

import silk_circuit
import silk_data_layer as dl


def setup_function(_fn):
    silk_circuit.http_breaker.reset()


def teardown_function(_fn):
    silk_circuit.http_breaker.reset()


def test_transport_timeout_opens_the_breaker():
    host = "api.worldbank.org"
    with patch.object(dl._session, "get", side_effect=requests.exceptions.Timeout("slow")):
        for _ in range(silk_circuit.http_breaker.threshold):
            try:
                dl._http_get(f"https://{host}/x")
            except requests.exceptions.RequestException:
                pass
    # After the threshold of transport timeouts the host fast-fails.
    assert silk_circuit.http_breaker.is_open(host)


class _SoftLimit(Exception):
    """Stand-in matching billiard.exceptions.SoftTimeLimitExceeded by module path."""


def test_soft_time_limit_is_reraised_not_swallowed(monkeypatch):
    # Make _is_worker_time_limit recognize our sentinel, as if billiard raised it.
    monkeypatch.setattr(dl, "_is_worker_time_limit", lambda e: isinstance(e, _SoftLimit))
    monkeypatch.setattr(dl, "_cached_get", lambda *a, **k: (_ for _ in ()).throw(_SoftLimit()))

    # comtrade_trade's broad handler must let the worker time limit propagate.
    try:
        raised = False
        try:
            dl.comtrade_trade("392010", "356", 2022)
        except _SoftLimit:
            raised = True
    except TypeError:
        # signature drift guard — fail loudly rather than silently pass
        raise
    assert raised, "SoftTimeLimitExceeded must propagate, not become a declared gap"


def test_ordinary_error_still_degrades_to_a_gap(monkeypatch):
    # A normal fetch error is still swallowed into a declared gap (unchanged).
    monkeypatch.setattr(dl, "_cached_get", lambda *a, **k: (_ for _ in ()).throw(OSError("net")))
    assert dl.comtrade_trade("392010", "356", 2022) is None

"""إعادة محاولة + backoff على الحالات العابرة (429/529) — resilience لنداء
الكاتب. بلاغ حي (كاتب التقرير، تقرير الكويت): نداء الكاتب — أثقل نداء، في ذيل
التشغيلة بعد استهلاك الحصّة — كان يفشل من أول رفض عابر (المزوّد بلا أي إعادة
محاولة) فيصير report=None → PRELIMINARY. هنا نُثبت أن 429/529 يُعاد بـbackoff
(كلفة رموز صفر: مرفوض قبل التوليد)، وأن غير العابر لا يُعاد، وأن استنفاد
المحاولات يطابق سلوك اليوم (None + خطأ مُسجَّل).

هرمتي بالكامل: requests.post مُحاكاة، time.sleep مُرقَّع (لا نوم فعلي)، بلا شبكة.
"""
import os
import contextlib

import requests
from unittest.mock import patch

import silk_llm_provider as lp


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
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _Resp:
    """ردّ HTTP مُحاكى — status_code + headers + json + raise_for_status."""

    def __init__(self, status, body=None, headers=None, text=""):
        self.status_code = status
        self._body = body or {"stop_reason": "end_turn",
                              "content": [{"type": "text", "text": "OK"}]}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


def _seq_post(responses):
    """side_effect يُرجع الردود بالترتيب — يحاكي 429 ثم 200 مثلاً."""
    it = iter(responses)

    def _post(url, timeout, headers, json):
        return next(it)
    return _post


def _raise_then(exc, then_resp):
    """side_effect يرمي `exc` أول مرّة ثم يُرجع `then_resp` — يحاكي فشل اتصال عابر."""
    calls = {"n": 0}

    def _post(url, timeout, headers, json):
        calls["n"] += 1
        if calls["n"] == 1:
            raise exc
        return then_resp
    return _post


def test_retries_on_connect_timeout_then_succeeds():
    """بلاغ الكويت: ConnectTimeout عابر (فشل اتصال سريع) ثم 200 => ينجح بعد
    إعادة محاولة. هذا نوع فشل الكاتب الفعلي الذي لم يغطّه retry الـ429/529."""
    exc = requests.exceptions.ConnectTimeout("Connection timed out.")
    with _env(ANTHROPIC_API_KEY="k"), \
         patch("requests.post", side_effect=_raise_then(exc, _Resp(200))), \
         patch("time.sleep") as slept:
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out == "OK"
    assert lp.last_error() is None
    assert slept.call_count == 1


def test_retries_on_connection_error_then_succeeds():
    """ConnectionError عابر ثم 200 => ينجح بعد إعادة محاولة."""
    exc = requests.exceptions.ConnectionError("Connection reset by peer")
    with _env(ANTHROPIC_API_KEY="k"), \
         patch("requests.post", side_effect=_raise_then(exc, _Resp(200))), \
         patch("time.sleep"):
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out == "OK"


def test_read_timeout_is_NOT_retried_fails_immediately():
    """ReadTimeout (مهلة قراءة بطيئة — النموذج ولّد فعلاً) **لا يُعاد** — إعادته
    تحرق رموزاً بلا طائل. يفشل فوراً بلا نوم، وlast_error يحمل النوع."""
    exc = requests.exceptions.ReadTimeout("Read timed out.")
    with _env(ANTHROPIC_API_KEY="k"), \
         patch("requests.post", side_effect=_raise_then(exc, _Resp(200))), \
         patch("time.sleep") as slept:
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out is None
    assert slept.call_count == 0
    assert lp.last_error()["type"] == "ReadTimeout"


def test_persistent_connect_timeout_exhausts_then_returns_none():
    """ConnectTimeout دائم => بعد استنفاد المحاولات: None + last_error بنوعه
    (مطابق للسلوك بعد الاستنفاد)، وينام max_retries مرّة."""
    exc = requests.exceptions.ConnectTimeout("down")

    def _always(url, timeout, headers, json):
        raise exc
    with _env(ANTHROPIC_API_KEY="k", SILK_LLM_MAX_RETRIES="2"), \
         patch("requests.post", side_effect=_always), \
         patch("time.sleep") as slept:
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out is None
    assert lp.last_error()["type"] == "ConnectTimeout"
    assert slept.call_count == 2


def test_retries_on_429_then_succeeds():
    """429 عابر ثم 200 => النداء ينجح بعد إعادة محاولة واحدة (لا None)."""
    seq = [_Resp(429), _Resp(200)]
    # لا نضبط RETRY_BASE_S=0 هنا: نريد backoff>0 كي يُستدعى sleep (المُرقَّع) مرّة.
    with _env(ANTHROPIC_API_KEY="k"), \
         patch("requests.post", side_effect=_seq_post(seq)), \
         patch("time.sleep") as slept:
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out == "OK"
    assert lp.last_error() is None
    assert slept.call_count == 1


def test_retries_on_529_overload_then_succeeds():
    """529 (ازدحام Anthropic) عابر ثم 200 => ينجح بعد إعادة محاولة."""
    seq = [_Resp(529), _Resp(200)]
    with _env(ANTHROPIC_API_KEY="k", SILK_LLM_RETRY_BASE_S="0"), \
         patch("requests.post", side_effect=_seq_post(seq)), \
         patch("time.sleep"):
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out == "OK"


def test_exhausts_retries_on_persistent_429_matches_today_behavior():
    """429 دائم => بعد استنفاد المحاولات: None + last_error يحمل status 429
    (مطابق لسلوك اليوم بعد الاستنفاد) وينام max_retries مرّة."""
    always = [_Resp(429) for _ in range(10)]
    with _env(ANTHROPIC_API_KEY="k", SILK_LLM_MAX_RETRIES="2"), \
         patch("requests.post", side_effect=_seq_post(always)), \
         patch("time.sleep") as slept:
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out is None
    err = lp.last_error()
    assert err is not None and err.get("status_code") == 429
    assert slept.call_count == 2      # max_retries محاولات إعادة


def test_no_retry_when_max_retries_zero():
    """SILK_LLM_MAX_RETRIES=0 => سلوك اليوم بالضبط: أول 429 يفشل بلا نوم."""
    with _env(ANTHROPIC_API_KEY="k", SILK_LLM_MAX_RETRIES="0"), \
         patch("requests.post", side_effect=_seq_post([_Resp(429)])), \
         patch("time.sleep") as slept:
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out is None
    assert slept.call_count == 0


def test_no_retry_on_non_retryable_400():
    """400 (حمولة سيئة) ليس عابراً => يفشل فوراً بلا إعادة محاولة."""
    with _env(ANTHROPIC_API_KEY="k"), \
         patch("requests.post", side_effect=_seq_post([_Resp(400), _Resp(200)])), \
         patch("time.sleep") as slept:
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out is None
    assert slept.call_count == 0
    assert lp.last_error().get("status_code") == 400


def test_retry_after_header_respected():
    """ترويسة Retry-After (Anthropic يرسلها على 429) تحدّد مدّة النوم لا الـbackoff."""
    seq = [_Resp(429, headers={"retry-after": "5"}), _Resp(200)]
    with _env(ANTHROPIC_API_KEY="k"), \
         patch("requests.post", side_effect=_seq_post(seq)), \
         patch("time.sleep") as slept:
        out = lp.AnthropicProvider().complete("s", "u", 100, "m", 300)
    assert out == "OK"
    slept.assert_called_once_with(5.0)


def test_complete_tools_also_retries_on_transient():
    """حلقة الأدوات (البعثات) تنتفع بنفس الـresilience — 429 ثم 200 => يرجع data."""
    body = {"content": [{"type": "text", "text": "x"}], "stop_reason": "end_turn"}
    seq = [_Resp(529), _Resp(200, body=body)]
    with _env(ANTHROPIC_API_KEY="k", SILK_LLM_RETRY_BASE_S="0"), \
         patch("requests.post", side_effect=_seq_post(seq)), \
         patch("time.sleep"):
        out = lp.AnthropicProvider().complete_tools("s", [], None, 100, "m", 300)
    assert out == body


def test_retry_after_parser_caps_and_rejects_garbage():
    """محلّل Retry-After: يقيّد بـcap، ويرفض القيمة غير الرقمية بأمان (None)."""
    assert lp.AnthropicProvider._retry_after(_Resp(429, headers={"retry-after": "999"})) == 60.0
    assert lp.AnthropicProvider._retry_after(_Resp(429, headers={"retry-after": "x"})) is None
    assert lp.AnthropicProvider._retry_after(_Resp(429)) is None

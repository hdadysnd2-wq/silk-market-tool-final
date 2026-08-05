"""تنقيح تسرّب المفاتيح (C3 · HIGH-4/5) — provider-key leak redaction locks.

يقفل أن مفتاح مزوّدٍ مضبوطاً لا يتسرّب إلى ملاحظةٍ (قد تصل تقرير العميل) ولا إلى
سجلّ الخادم عند فشل الجلب في وكيلَي LocalPrice (مدفوع) وGoogle Maps (مجّاني).
المفتاح يركب سلسلة استعلام الرابط، فرسالة استثناء requests تضمّه — والإصلاح يبتر
سلسلة الاستعلام عبر `silk_redact.redact_url` قبل أي كتابة.

كلها هيرمتية — لا شبكة، لا مفاتيح حقيقية (نُجبر الفشل بـ mock على requests.get).
Run:  python3 -m pytest tests/test_key_redaction.py -q
"""
import contextlib
import logging
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_redact  # noqa: E402


@contextlib.contextmanager
def _env(**vals):
    """اضبط متغيرات بيئة مع استرجاع مضمون — set env vars, guaranteed restore."""
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


# ── وحدة redact_url ────────────────────────────────────────────────────────

def test_redact_url_strips_query_string_hiding_the_key():
    secret = "FAKE-SERPAPI-KEY-abc123def456"
    msg = ("HTTPError: 401 Unauthorized for url: "
           f"https://serpapi.com/search.json?engine=google_shopping&q=dates&api_key={secret}")
    out = silk_redact.redact_url(msg, secret=secret)
    assert secret not in out
    assert "<redacted>" in out
    # نُبقي أصل الرابط (نقطة النهاية) للتشخيص — the endpoint stays for debugging.
    assert "https://serpapi.com/search.json" in out


def test_redact_url_catches_encoded_key_the_naive_replace_would_miss():
    # المفتاح مُرمَّز في الرابط بينما القيمة الحرفية مختلفة — .replace(key) القديم
    # كان يفوّته؛ بتر سلسلة الاستعلام يحجبه بأي ترميز.
    secret = "FAKE-KEY-longenough-1234"
    encoded = "FAKE%2DKEY%2Dlongenough%2D1234"
    msg = f"ConnectionError for url: https://maps.googleapis.com/x?query=a&key={encoded}"
    out = silk_redact.redact_url(msg, secret=secret)
    assert encoded not in out
    assert secret not in out


def test_redact_url_masks_bare_literal_secret_when_long():
    secret = "TOPSECRET-longenough-key"
    out = silk_redact.redact_url(f"auth failed with token {secret} rejected", secret=secret)
    assert secret not in out
    assert "***" in out


def test_redact_url_does_not_mangle_short_legitimate_text():
    # حارس الحدّ الأدنى (الدرس L2): سرّ قصير لا يشوّه نصاً مشروعاً يحتويه.
    out = silk_redact.redact_url("dates market in Morocco", secret="ma")
    assert out == "dates market in Morocco"


def test_redact_url_noop_on_plain_text():
    assert silk_redact.redact_url("no url here, nothing to redact") == \
        "no url here, nothing to redact"


# ── LocalPrice (مدفوع) — المفتاح لا يتسرّب لملاحظة ولا لسجلّ ────────────────

def test_localprice_failure_note_and_log_never_carry_the_key(caplog):
    import silk_localprice_agent as lp
    secret = "FAKE-LOCALPRICE-KEY-9f8e7d6c5b4a"

    def boom(*a, **k):
        raise RuntimeError(
            "HTTPSConnectionPool: Max retries exceeded with url: "
            f"/search.json?engine=google_shopping&q=dates&api_key={secret}")

    with _env(LOCALPRICE_API_KEY=secret), \
            mock.patch("requests.get", side_effect=boom), \
            caplog.at_level(logging.WARNING):
        findings = lp.retail_prices("dates", "ma")

    dp = findings[0]
    assert dp.value is None and dp.confidence == 0.0   # فجوة معلنة لا اختلاق
    assert secret not in dp.note
    assert secret not in caplog.text
    assert "fetch failed" in dp.note


# ── Google Maps (مجّاني، مساره يغذّي تقرير العميل) — الأخطر ──────────────────

def test_maps_failure_note_log_and_opslog_never_carry_the_key(caplog):
    import silk_maps_agent as gm
    secret = "AIzaFAKE-GMAPS-KEY-9f8e7d6c5b4a"
    recorded: list[str] = []

    def boom(*a, **k):
        raise RuntimeError(
            "HTTPError: 403 Client Error for url: "
            f"https://maps.googleapis.com/maps/api/place/textsearch/json?query=dates&key={secret}")

    # التقط ما يُكتب في سجلّ التشغيل للتأكّد أنه منقّح أيضاً.
    with _env(GOOGLE_MAPS_API_KEY=secret), \
            mock.patch("requests.get", side_effect=boom), \
            mock.patch("silk_ops_log.record_service_failure",
                       side_effect=lambda svc, msg: recorded.append(msg)), \
            caplog.at_level(logging.WARNING):
        findings = gm.find_places("dates distributor", "ma")

    dp = findings[0]
    assert dp.value is None and dp.confidence == 0.0   # فجوة معلنة لا اختلاق
    assert secret not in dp.note
    assert secret not in caplog.text
    assert recorded and all(secret not in m for m in recorded)

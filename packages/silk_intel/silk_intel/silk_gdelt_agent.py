"""وكيل GDELT لسِلك — Silk GDELT news-headline research tool (V5 wave 1).

يجلب عناوين إخبارية حقيقية من GDELT DOC 2.0 API — مجاني وبلا مفتاح
(founding principle: لا اختلاق، وأي فشل يعيد DataPoint موسوماً). يُستهلك
كأداة داخل حلقة الوكيل اللغوي (`silk_llm_runtime`) لمهمة "المخاطر
والأخبار" — كل نص عائد يمرّ عبر `silk_ai_judge._isolate` قبل الوصول لكلود
(المصدر خارجي، قد يحوي نصّ حقن).
"""
from __future__ import annotations

import logging
import time

import requests

from silk_data_layer import DataPoint, _today

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMEOUT = 30
# محاولة إعادة واحدة مهذّبة عند 429 (الموجة ٩) — لا سيل إعادة محاولات؛
# تحترم Retry-After إن أعادته GDELT، وإلا تأخير ثابت قصير. فشل المحاولة
# الثانية = فجوة معلنة مميَّزة (429 لا خطأ عام) — لا اختلاق، لا إلحاح.
_RETRY_DELAY_S = 2.0
# ترويسة متصفح — بلاغ حي (الموجة ٨): فشل GDELT على نشر Railway بلا تفاصيل
# مؤكَّدة (لا وصول شبكي من بيئة التطوير لإعادة الإنتاج حياً)؛ عدّة أطراف
# API عامة تحجب عميل requests الافتراضي (python-requests/x.y) أو نطاقات
# IP مراكز البيانات السحابية — إصلاح معقول ومنخفض المخاطر بلا أثر جانبي
# على الاستجابة الناجحة، غير مؤكَّد أنه السبب الجذري الفعلي هنا صراحة.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SilkMarketIntel/1.0; "
                         "+https://github.com/hdadysnd2-wq)"}


def gdelt_news(query: str, market: str = "", months: int = 12,
              max_records: int = 10) -> list[DataPoint]:
    """عناوين GDELT لآخر أشهر — recent headlines for a query (+ optional market).

    Standalone helper, keyless. Returns a list of DataPoint(value={"title",
    "url", "date", "domain"}) on success, or a single DataPoint(value=None,
    confidence=0.0) on an empty query / network failure / no results — never
    invents a headline (founding principle).
    """
    q = (query or "").strip()
    if not q:
        return [DataPoint(None, "GDELT", 0.0, "empty query — no search", _today())]
    full_query = f"{q} {market}".strip() if market else q
    months = max(1, min(int(months or 12), 24))
    params = {
        "query": full_query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(max(1, min(int(max_records or 10), 50))),
        "timespan": f"{months}m",
        "sort": "datedesc",
    }
    try:
        resp = requests.get(_ENDPOINT, params=params, headers=_HEADERS,
                            timeout=_TIMEOUT)
        if resp.status_code == 429:
            # تراجُع مهذّب + محاولة واحدة فقط — لا إلحاح على مصدر يحجب أصلاً.
            retry_after = resp.headers.get("Retry-After", "")
            delay = (float(retry_after) if retry_after.replace(".", "", 1)
                     .isdigit() else _RETRY_DELAY_S)
            log.warning("GDELT 429 for %r — one polite retry in %.1fs",
                       full_query, min(delay, 15.0))
            time.sleep(min(delay, 15.0))
            resp = requests.get(_ENDPOINT, params=params, headers=_HEADERS,
                                timeout=_TIMEOUT)
        if resp.status_code == 429:
            note = (f"GDELT rate-limited (HTTP 429) for {full_query!r} حتى "
                    "بعد محاولة مهذّبة واحدة — على الأرجح حجب نطاق IP "
                    "(بيئة استضافة سحابية)؛ استخدم web_search كبديل موثَّق.")
            log.warning(note)
            return [DataPoint(None, "GDELT", 0.0, note, _today())]
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 — never raise to caller
        note = f"GDELT fetch failed for {full_query!r}: {type(e).__name__}: {e}"
        log.warning(note)
        try:  # عائلة C (Wave 1.5): لا فشلٌ صامت — أعلِنه للمشغّل.
            import silk_ops_log
            silk_ops_log.record_service_failure("gdelt", note)
        except Exception:  # noqa: BLE001
            pass
        return [DataPoint(None, "GDELT", 0.0, note, _today())]
    try:
        payload = resp.json()
    except ValueError as e:
        # ردّ HTTP ناجح لكن ليس JSON — بلاغ حي: هذا نمط شائع لحجب WAF/بوابة
        # حماية (صفحة HTML بدل JSON) بخلاف فشل شبكة صريح؛ ملاحظة مميَّزة
        # كي يُشخَّص لاحقاً دون خلطه بعطل اتصال عادي.
        note = (f"GDELT returned non-JSON body for {full_query!r} "
                f"(HTTP {resp.status_code}, content-type="
                f"{resp.headers.get('content-type', '?')!r}) — {e}")
        log.warning(note)
        return [DataPoint(None, "GDELT", 0.0, note, _today())]

    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not articles:
        return [DataPoint(None, "GDELT", 0.0,
                          f"no headlines for {full_query!r} in last {months}m",
                          _today())]

    out: list[DataPoint] = []
    for art in articles[:max_records]:
        title = (art.get("title") or "").strip()
        if not title:
            continue
        out.append(DataPoint(
            {"title": title, "url": art.get("url", ""),
             "date": art.get("seendate", ""), "domain": art.get("domain", "")},
            "GDELT", 0.6,
            f"headline for query {full_query!r} (last {months}m)", _today()))
    if not out:
        return [DataPoint(None, "GDELT", 0.0,
                          f"articles returned but none carried a title for "
                          f"{full_query!r}", _today())]
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = gdelt_news("dates exports", "Nigeria", months=12, max_records=5)
    for dp in res:
        print(f"  [{dp.confidence}] {dp.value if dp.value is None else dp.value.get('title')}")

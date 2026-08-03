"""وكيل أخبار قوقل RSS لسِلك — Silk Google News RSS connector + news fallback chain.

يجلب عناوين إخبارية حقيقية من خدمة Google News RSS العامة — **مجاني وبلا
مفتاح** (news.google.com/rss/search). الغرض: حلقة تعطيلٍ نظيفة (WS8) — حين
تفشل GDELT (429/حجب IP سحابي/لا نتيجة) لا يسقط الخط مباشرةً إلى فجوة، بل
يتدرّج: **GDELT → Google News RSS → Serper** — والفجوة تُعلَن فقط بعد استنفاد
السلسلة كاملةً (المبدأ التأسيسي: لا اختلاق، وأي فشل يعيد `DataPoint` موسوماً).

Fetches real news headlines from the public Google News RSS endpoint — free,
keyless. Its role is a graceful-degradation ladder (WS8): a GDELT failure no
longer drops straight to a declared gap; the chain falls through to Google
News RSS, then to Serper web-search, and a gap is emitted only when every link
fails. Output DataPoint shape mirrors `silk_gdelt_agent.gdelt_news`
(value={"title","url","date","domain","source_id"}) so downstream isolation
and rendering stay uniform. Every returned string is external text and must be
passed through `silk_ai_judge._isolate` before reaching Claude.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

from silk_data_layer import DataPoint, _today

log = logging.getLogger(__name__)

_ENDPOINT = "https://news.google.com/rss/search"
_TIMEOUT = 20
# ترويسة متصفح — نفس منطق GDELT: عدّة أطراف API عامة تحجب عميل requests
# الافتراضي؛ إصلاح منخفض المخاطر بلا أثر جانبي على الاستجابة الناجحة.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SilkMarketIntel/1.0; "
                         "+https://github.com/hdadysnd2-wq)"}

# مُعرِّف المصدر العمومي (WS9) — الاسم المنشور في قسم المراجع، لا وسم داخلي.
SOURCE_ID = "Google News"


def _rss_ceid(gl: str, hl: str) -> tuple[str, str, str]:
    """يبني معاملات اللغة/الدولة لخدمة RSS — (hl, gl, ceid).

    gl = رمز الدولة ISO 3166-1 alpha-2 (مثل ``US``/``NL``)، hl = رمز اللغة
    (مثل ``en``/``ar``). فارغ => الافتراضي الإنجليزي/الأمريكي (سلوك متوقّع).
    """
    country = (gl or "US").strip().upper()
    lang = (hl or "en").strip().lower()
    return f"{lang}-{country}", country, f"{country}:{lang}"


def _domain_of(link: str, source_url: str) -> str:
    """اسم النطاق من رابط المقال (أو رابط المصدر) — بلا اختلاق، فارغ إن تعذّر."""
    for candidate in (source_url, link):
        raw = (candidate or "").strip()
        if not raw:
            continue
        host = raw.split("://", 1)[-1].split("/", 1)[0].strip()
        if host:
            return host[4:] if host.startswith("www.") else host
    return ""


def google_news_rss(query: str, market: str = "", months: int = 12,
                    max_records: int = 10, gl: str = "", hl: str = "") -> list[DataPoint]:
    """عناوين Google News RSS لآخر أشهر — recent headlines for a query (+ market).

    Standalone helper, keyless. Returns a list of DataPoint(value={"title",
    "url", "date", "domain", "source_id"}) on success, or a single
    DataPoint(value=None, confidence=0.0) on an empty query / network failure /
    non-XML body / no results — never invents a headline (founding principle).
    """
    q = (query or "").strip()
    if not q:
        return [DataPoint(None, SOURCE_ID, 0.0, "empty query — no search", _today())]
    full_query = f"{q} {market}".strip() if market else q
    months = max(1, min(int(months or 12), 24))
    # مرشّح زمني عبر عامل بحث قوقل الأصيل ``when:Nm`` — لا اختلاق، أطر الخدمة.
    search_terms = f"{full_query} when:{months}m"
    hl_param, gl_param, ceid = _rss_ceid(gl, hl)
    url = (f"{_ENDPOINT}?q={quote_plus(search_terms)}"
           f"&hl={hl_param}&gl={gl_param}&ceid={ceid}")
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 — never raise to caller
        note = (f"Google News fetch failed for {full_query!r}: "
                f"{type(e).__name__}: {e}")
        log.warning(note)
        try:  # عائلة C (Wave 1.5): لا فشلٌ صامت — أعلِنه للمشغّل.
            import silk_ops_log
            silk_ops_log.record_service_failure("google_news", note)
        except Exception:  # noqa: BLE001
            pass
        return [DataPoint(None, SOURCE_ID, 0.0, note, _today())]

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        # ردّ ناجح لكن ليس XML سليماً — نمط شائع لصفحة حجب/خطأ HTML؛
        # ملاحظة مميَّزة كي يُشخَّص لاحقاً دون خلطه بعطل اتصال عادي.
        note = (f"Google News returned non-XML body for {full_query!r} "
                f"(HTTP {resp.status_code}, content-type="
                f"{resp.headers.get('content-type', '?')!r}) — {e}")
        log.warning(note)
        return [DataPoint(None, SOURCE_ID, 0.0, note, _today())]

    items = root.findall(".//item")
    if not items:
        return [DataPoint(None, SOURCE_ID, 0.0,
                          f"no headlines for {full_query!r} in last {months}m",
                          _today())]

    out: list[DataPoint] = []
    for item in items[:max_records]:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        source_url = src_el.get("url", "") if src_el is not None else ""
        out.append(DataPoint(
            {"title": title, "url": link, "date": pub,
             "domain": _domain_of(link, source_url), "source_id": SOURCE_ID},
            SOURCE_ID, 0.55,
            f"headline for query {full_query!r} (last {months}m)", _today()))
    if not out:
        return [DataPoint(None, SOURCE_ID, 0.0,
                          f"items returned but none carried a title for "
                          f"{full_query!r}", _today())]
    return out


def _has_headline(results: list[DataPoint]) -> bool:
    """هل تحمل النتيجة عنواناً حقيقياً واحداً على الأقل؟ (لا فجوة صرفة)."""
    return any(dp.value for dp in (results or []))


def news_with_fallback(query: str, market: str = "", months: int = 12,
                       max_records: int = 10, gl: str = "", hl: str = "",
                       ) -> list[DataPoint]:
    """سلسلة أخبار متدرّجة — GDELT → Google News RSS → Serper (WS8).

    تُرجِع أول تِيرٍ يحمل عناوين حقيقية، وإلا تُعلِن فجوةً واحدةً صريحة تسمّي
    الروابط المُستنفَدة (لا اختلاق، عقد عدم الاختلاق). كل تِير موسومٌ بمصدره
    العمومي في `DataPoint.source` ليظهر صحيحاً في قسم المراجع (WS9).

    Walks the chain lazily (imports per link, the repo norm) and returns the
    first link that yields at least one real headline. A declared GAP is emitted
    only when GDELT, Google News RSS, and Serper all fail — never a fabricated
    headline. The final gap note lists exactly which links were attempted so the
    exhaustion is auditable.
    """
    attempted: list[str] = []

    # 1) GDELT (القائم) — المصدر الأساسي.
    try:
        from silk_gdelt_agent import gdelt_news
        attempted.append("GDELT")
        gd = gdelt_news(query, market=market, months=months,
                        max_records=max_records)
        if _has_headline(gd):
            return gd
    except Exception as e:  # noqa: BLE001 — never raise; fall through the chain.
        log.warning("news chain: GDELT link raised, falling through: %r", e)

    # 2) Google News RSS (مجاني، بلا مفتاح) — التِير الأوسط الجديد.
    attempted.append(SOURCE_ID)
    gn = google_news_rss(query, market=market, months=months,
                         max_records=max_records, gl=gl, hl=hl)
    if _has_headline(gn):
        return gn

    # 3) Serper (web_search) — الملاذ الأخير الموثَّق.
    try:
        from silk_websearch_agent import web_search
        attempted.append("Web Search")
        q = (query or "").strip()
        news_q = f"{q} {market} news".strip() if market else f"{q} news".strip()
        ws = web_search(news_q, num=max_records, gl=(gl or None), hl=(hl or None))
        if _has_headline(ws):
            return ws
    except Exception as e:  # noqa: BLE001 — never raise; declare the gap below.
        log.warning("news chain: Serper link raised: %r", e)

    # استُنفدت السلسلة كاملةً — فجوة معلنة واحدة تسمّي الروابط المُجرَّبة.
    note = ("لا عناوين إخبارية بعد استنفاد السلسلة كاملةً "
            f"({' → '.join(attempted)}) — فجوة معلنة، لا اختلاق.")
    return [DataPoint(None, SOURCE_ID, 0.0, note, _today())]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for dp in news_with_fallback("peanut butter", "Netherlands", months=12,
                                 max_records=5, gl="NL", hl="en"):
        got = dp.value if dp.value is None else dp.value.get("title")
        print(f"  [{dp.source} {dp.confidence}] {got}")

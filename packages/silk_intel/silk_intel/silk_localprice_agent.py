"""وكيل أسعار السوق المحلي لسِلك — Silk local retail-price agent (docx layer 10).

يغطّي صف «المتاجر المحلية» في دليل المصادر: الأسعار الفعلية في متاجر التجزئة
(أمازون، نون، جوميا…) + مقارنة سعرك الخاص بها. يعطيك سعر بيع المنتج الفعلي في
السوق المستهدف — عنصر حاسم لتقدير هامش الربح بعد الاستيراد والرسوم.

Returns the product's REAL local retail price points by querying a configured
price/shopping API (LOCALPRICE_API_KEY + LOCALPRICE_API_URL — e.g. a SerpApi
Google-Shopping endpoint or any JSON service returning priced listings). With no
key OR a network/format failure it returns a provenance-tagged None and never
invents a price (founding principle). 'requests' is lazy-imported so the module
imports offline and keyless with no side effects.

ملاحظة صادقة عن «الأكثر مبيعاً» — honest note on "best-sellers": is_best_seller
on a listing reflects a badge/tag the PROVIDER itself returned (e.g. a shopping
API's "bestseller" flag) — never inferred from price or position. No retail
platform publishes actual UNITS-SOLD numbers via a public API, so this module
never reports a sales count — only a real badge when the provider sends one, or
False otherwise. compare_own_price() gives you a price-positioning comparison
(percentile vs. real local listings) — not a sales-volume comparison.
"""
from __future__ import annotations

import logging
import os

from silk_data_layer import DataPoint, _today
from silk_agents import BaseAgent, AgentReport

log = logging.getLogger(__name__)

# نقطة نهاية أسعار التجزئة — overridable so a provider change needs no code edit.
# الافتراضي SerpApi (Google Shopping) لأنه يرجّع listings بأسعار وعملة ومتجر.
_PRICE_URL = os.environ.get(
    "LOCALPRICE_API_URL", "https://serpapi.com/search.json").strip()
_TIMEOUT = 30


_BESTSELLER_KEYS = ("bestseller", "is_bestseller", "best_seller")


def _is_bestseller(it: dict) -> bool:
    """شارة «الأكثر مبيعاً» الحقيقية فقط — real badge only, from the provider's
    own payload; never inferred from price/rank/position. False when the
    provider sends nothing (no fabrication, no guessing)."""
    for k in _BESTSELLER_KEYS:
        v = it.get(k)
        if isinstance(v, bool) and v:
            return True
        if isinstance(v, str) and v.strip():
            return True
    tag = str(it.get("tag") or "").lower()
    if "best seller" in tag or "bestseller" in tag:
        return True
    for ext in it.get("extensions") or []:
        if isinstance(ext, str) and ("best seller" in ext.lower()
                                     or "bestseller" in ext.lower()):
            return True
    return False


def _extract(payload: dict) -> list[dict]:
    """التقط القوائم المسعّرة من ردّ المزوّد — pull priced listings from the payload.

    Supports SerpApi's `shopping_results` and a generic `results`/`items` list.
    Each item -> {title, price, currency, store, link, is_best_seller} using
    only present fields; items with no usable price are skipped (never
    fabricated). is_best_seller is True only when the provider itself flagged
    the listing (badge/tag/extension) — never a units-sold count (no platform
    publishes that publicly).
    """
    items = (payload.get("shopping_results")
             or payload.get("results") or payload.get("items") or [])
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        price = (it.get("extracted_price") if it.get("extracted_price") is not None
                 else it.get("price"))
        if price in (None, ""):
            continue
        out.append({
            "title": it.get("title") or it.get("name"),
            "price": price,
            "currency": it.get("currency"),
            "store": it.get("source") or it.get("store") or it.get("seller"),
            "link": it.get("link") or it.get("product_link"),
            "is_best_seller": _is_bestseller(it),
        })
    return out


def retail_prices(query: str, market: str | None = None) -> list[DataPoint]:
    """أسعار التجزئة المحلية — real local retail price points for a product.

    Each priced listing -> DataPoint(value={title, price, currency, store, link}).
    No key -> a single DataPoint(None, 0.0, "<requires key>"). On network/API
    failure or empty result -> [DataPoint(None, ...)] (caller flags it). The agent
    NEVER invents a price: a missing source means value=None, confidence=0.0.
    """
    key = os.environ.get("LOCALPRICE_API_KEY", "").strip()
    if not key:
        log.warning("LOCALPRICE_API_KEY not set — local retail prices unavailable")
        return [DataPoint(None, "Local retail", 0.0,
                          "local prices require LOCALPRICE_API_KEY "
                          "(e.g. a SerpApi Google-Shopping key)", _today())]
    q = (query or "").strip()
    if not q:
        return [DataPoint(None, "Local retail", 0.0,
                          "empty query — no price lookup", _today())]
    try:
        import requests  # lazy: keeps import offline-safe and keyless
    except ImportError:
        log.warning("requests not installed — local retail prices unavailable")
        return [DataPoint(None, "Local retail", 0.0,
                          "requests unavailable", _today())]
    # معاملات SerpApi (افتراضي) — engine=google_shopping; gl يحيّز السوق المستهدف.
    params = {"engine": "google_shopping", "q": q, "api_key": key}
    if market:
        params["gl"] = market.lower()  # ccTLD/country bias, e.g. 'ma' for Morocco
    try:
        r = requests.get(_PRICE_URL, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:  # noqa: BLE001 — never raise to caller
        log.warning("local price fetch failed (q=%r, market=%s): %s", q, market, e)
        return [DataPoint(None, "Local retail", 0.0,
                          f"local price fetch failed: {e}", _today())]
    listings = _extract(payload)
    if not listings:
        return [DataPoint(None, "Local retail", 0.0,
                          f"no priced listings for '{q}'", _today())]
    findings: list[DataPoint] = []
    for it in listings:
        cur = f" {it['currency']}" if it.get("currency") else ""
        badge = " [best-seller]" if it.get("is_best_seller") else ""
        findings.append(DataPoint(
            it, "Local retail", 0.6,
            f"{it.get('title') or 'listing'} @ {it['price']}{cur}"
            + (f" ({it['store']})" if it.get("store") else "") + badge,
            _today()))
    return findings


def compare_own_price(own_price: float | None, findings: list[DataPoint]) -> dict:
    """قارن سعرك بقوائم السوق المحلي المرصودة — compare YOUR price to the local
    retail listings already fetched by retail_prices() (no extra network call).

    Returns {your_price, listings_count, market_min, market_max, market_avg,
    cheaper_than_pct, verdict, note}. cheaper_than_pct is the % of the observed
    listings priced HIGHER than yours (i.e. you're cheaper than that share of
    the observed market) — a positioning signal, not a sales-volume comparison.
    Never fabricates: with no listings or no own_price, the numeric fields stay
    None and `note` explains why.
    """
    prices: list[float] = []
    for dp in findings or []:
        v = dp.value
        raw = v.get("price") if isinstance(v, dict) else None
        try:
            prices.append(float(raw))
        except (TypeError, ValueError):
            continue

    if not prices:
        return {"your_price": own_price, "listings_count": 0,
                "market_min": None, "market_max": None, "market_avg": None,
                "cheaper_than_pct": None, "verdict": None,
                "note": "لا توجد قوائم أسعار محلية كافية للمقارنة — "
                        "no local listings available to compare against"}

    market_avg = round(sum(prices) / len(prices), 2)
    if own_price is None:
        return {"your_price": None, "listings_count": len(prices),
                "market_min": min(prices), "market_max": max(prices),
                "market_avg": market_avg, "cheaper_than_pct": None,
                "verdict": None,
                "note": "أدخل سعرك لمقارنته بالسوق — enter your price to compare"}

    n = len(prices)
    cheaper_than_pct = round(100 * sum(1 for p in prices if p > own_price) / n, 1)
    verdict = (f"تنافسي — أرخص من {cheaper_than_pct}% من القوائم المرصودة"
               if cheaper_than_pct >= 50 else
               f"أعلى من السوق — أرخص من {cheaper_than_pct}% فقط من القوائم المرصودة")
    return {"your_price": own_price, "listings_count": n,
            "market_min": min(prices), "market_max": max(prices),
            "market_avg": market_avg, "cheaper_than_pct": cheaper_than_pct,
            "verdict": verdict,
            "note": "مقارنة مبدئية على القوائم المرصودة فقط، ليست شاملة كل "
                    "السوق — preliminary, over observed listings only."}


def suggest_price(findings: list[DataPoint], cost_per_unit: float | None = None,
                  tariff_pct: float | None = None,
                  shipping_per_unit: float | None = None) -> dict:
    """اقترح نطاق تسعير من القوائم المرصودة — recommended price band (P1-6).

    مواصفة المالك: compare_own_price تُموضِع سعراً يُدخله المستخدم لكنها لا
    توصي بسعر أبداً — هذه تسدّ الفجوة. النطاق مشتق حصراً من إحصاءات القوائم
    المرصودة (الربيع الأول → الوسيط: منافس دون أغلب السوق) مرفوعاً عند
    الحاجة إلى أرضية التكلفة بعد الرسوم والشحن (إن أدخلها المستخدم) —
    معادلات معلنة في rationale، لا رقم من خارج المرصود والمدخلات.
    بلا قوائم => كل الحقول الرقمية None مع note يشرح السبب (لا اختلاق).

    Returns {suggested_min, suggested_max, landed_cost_floor,
    margin_at_min_pct, margin_at_max_pct, basis{...}, rationale, note}.
    """
    prices: list[float] = []
    for dp in findings or []:
        v = dp.value
        raw = v.get("price") if isinstance(v, dict) else None
        try:
            p = float(raw)
        except (TypeError, ValueError):
            continue
        if p > 0:
            prices.append(p)

    empty = {"suggested_min": None, "suggested_max": None,
             "landed_cost_floor": None, "margin_at_min_pct": None,
             "margin_at_max_pct": None, "basis": None, "rationale": None}
    if not prices:
        return {**empty,
                "note": "لا قوائم أسعار مرصودة يُشتق منها نطاق — التوصية "
                        "السعرية تتطلب أسعار رفّ فعلية (الدراسة العميقة)"}

    prices.sort()
    n = len(prices)

    def _pct(q: float) -> float:
        """المئين بالاستيفاء الخطي — linear-interpolated percentile."""
        idx = q * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return round(prices[lo] + (prices[hi] - prices[lo]) * (idx - lo), 2)

    q1, median = _pct(0.25), _pct(0.5)
    market_avg = round(sum(prices) / n, 2)
    basis = {"listings_count": n, "market_min": prices[0],
             "market_max": prices[-1], "market_avg": market_avg,
             "q1": q1, "median": median}

    # أرضية التكلفة حتى الوصول — من مدخلات المستخدم فقط؛ غيابها = لا أرضية.
    floor = None
    if cost_per_unit is not None:
        floor = float(cost_per_unit) * (1.0 + float(tariff_pct or 0) / 100.0) \
            + float(shipping_per_unit or 0)
        floor = round(floor, 2)

    lo_band, hi_band = q1, median
    rationale_bits = [
        f"النطاق المقترح مشتق من {n} سعراً مرصوداً: من الربيع الأول "
        f"({q1}) إلى الوسيط ({median}) — تسعير منافس دون متوسط السوق "
        f"({market_avg})"]

    note = ("نطاق مشتق من القوائم المرصودة فقط — راجعه مقابل تكاليفك "
            "الفعلية قبل الاعتماد" if floor is None else None)
    if floor is not None:
        rationale_bits.append(
            f"أرضية التكلفة حتى الوصول: {floor} "
            "(التكلفة × (1 + التعريفة%) + الشحن — من مدخلاتك)")
        if floor >= prices[-1]:
            return {**empty, "landed_cost_floor": floor, "basis": basis,
                    "rationale": "؛ ".join(rationale_bits),
                    "note": "تكلفتك بعد الرسوم والشحن أعلى من كل الأسعار "
                            "المرصودة في السوق — لا نطاق ربحي عند هذه "
                            "التكلفة؛ أعد النظر في التكلفة أو السوق"}
        if floor > lo_band:
            lo_band = floor
            rationale_bits.append("رُفع الحد الأدنى إلى أرضية التكلفة "
                                  "للحفاظ على هامش موجب")
        if hi_band < lo_band:
            hi_band = min(market_avg, prices[-1])
            rationale_bits.append("وُسّع الحد الأعلى إلى متوسط السوق لأن "
                                  "الأرضية تجاوزت الوسيط")
        if hi_band < lo_band:
            return {**empty, "landed_cost_floor": floor, "basis": basis,
                    "rationale": "؛ ".join(rationale_bits),
                    "note": "الأرضية تجاوزت متوسط السوق — الهامش الموجب "
                            "غير قابل للتحقيق ضمن الأسعار المرصودة"}

    def _margin(sell: float) -> float | None:
        if floor is None:
            return None
        return round((sell - floor) / sell * 100, 1) if sell > 0 else None

    return {"suggested_min": round(lo_band, 2),
            "suggested_max": round(hi_band, 2),
            "landed_cost_floor": floor,
            "margin_at_min_pct": _margin(lo_band),
            "margin_at_max_pct": _margin(hi_band),
            "basis": basis, "rationale": "؛ ".join(rationale_bits),
            "note": note or "توصية مبدئية على القوائم المرصودة فقط — "
                            "ليست شاملة كل السوق"}


class LocalPriceAgent(BaseAgent):
    """وكيل أسعار السوق المحلي — actual retail prices/best-sellers in-market."""

    PAID = True
    PREF_KEY = "pricing"
    SOURCE = "Local retail"

    def __init__(self) -> None:
        super().__init__("LocalPriceAgent")

    def _execute(self, task: dict) -> AgentReport:
        """اجلب الأسعار الفعلية في السوق — fetch real in-market retail prices.

        task keys: query (product, optionally + market words), market (ccTLD
        bias like 'ma', optional). Missing key / network fail -> failed report,
        never a fabricated price.
        """
        query = task.get("query", "")
        market = task.get("market")
        findings = retail_prices(query, market)
        real = [f for f in findings if f.value is not None]
        if not real:
            note = findings[0].note if findings else "no query"
            return AgentReport(self.name, findings, True,
                               f"لا أسعار محلية — no local price data ({note})")
        return AgentReport(self.name, real, False,
                           f"{len(real)} local price listing(s) for '{query}'")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk LocalPriceAgent — degrades gracefully offline / without key "
          "(no fabricated prices)")
    report = LocalPriceAgent().run({"query": "تمور", "market": "ma"})
    flag = "FAILED" if report.failed else "ok"
    print(f"  [{flag}] {report.agent_name}: {report.summary}")
    for f in report.findings:
        print(f"    value={f.value} conf={f.confidence} note={f.note}")

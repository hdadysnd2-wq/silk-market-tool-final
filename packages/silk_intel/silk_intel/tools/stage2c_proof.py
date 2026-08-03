"""برهان Stage 2C — إعادة تشغيل حالتَي الاختبار وقياس التباعد وإسهام المصادر.

الوضعان:
  --hermetic  بدائل HTTP واقعية الشكل عند حدود requests (بيئات بلا شبكة) —
              موسومة في التقرير الناتج كبرهان hermetic لا live.
  --live      الشبكة الحقيقية (نفّذه على النشر): يتطلب SEARCH_API_KEY و
              GOOGLE_MAPS_API_KEY في بيئة الخادم و pytrends مثبتة.

المقاييس (معيار قبول GATE 2):
  * تباعد محتوى التقريرين (تمور→CHN مقابل عسل→DEU) ≥ 70%
  * إسهام حقائق فعلي (value≠None) من: World Bank، Serper، Google Maps، Trends

Usage:  python3 tools/stage2c_proof.py --hermetic | --live
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)

CASES = [
    {"name": "dates_CHN", "product": "تمور", "iso3": "CHN", "m49": "156",
     "hs6": "080410"},
    {"name": "honey_DEU", "product": "عسل", "iso3": "DEU", "m49": "276",
     "hs6": "040900"},
]

POLICY = dict(with_trends=True, with_tariffs=True, with_faostat=True,
              with_requirements=True, with_trend=False,  # trend يضاعف كومتريد
              with_competitors=True, with_channels=True, with_importers=True,
              with_risk=True, with_websearch=True, with_maps=True)


def _facts_by_source(obj, acc):
    if isinstance(obj, dict):
        if "source" in obj and "value" in obj:
            s = str(obj.get("source")); a = acc.setdefault(s, [0, 0])
            a[0 if obj.get("value") is not None else 1] += 1
        for v in obj.values():
            _facts_by_source(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _facts_by_source(v, acc)
    elif hasattr(obj, "value") and hasattr(obj, "source"):
        s = str(obj.source); a = acc.setdefault(s, [0, 0])
        a[0 if obj.value is not None else 1] += 1
    for attr in ("components", "findings"):
        if hasattr(obj, attr):
            _facts_by_source(getattr(obj, attr), acc)


def _seed_hermetic_store(case):
    """بذور مخزن hermetic: تدفقات تجارية مختلفة لكل حالة (بدائل موسومة) +
    مؤشرات حقيقية من لقطة البنك الدولي المضمّنة + مؤشرات مخاطر (بدائل)."""
    import silk_store, silk_seed_data
    silk_store.migrate()
    flows = {
        "dates_CHN": [("WLD", 6.1e7), ("SAU", 1.9e7), ("IRN", 1.4e7),
                      ("TUN", 8.0e6), ("ARE", 6.5e6)],
        "honey_DEU": [("WLD", 2.9e8), ("UKR", 6.2e7), ("MEX", 4.4e7),
                      ("ARG", 3.9e7), ("CHN", 3.1e7)],
    }[case["name"]]
    silk_store.upsert_trade_flows([
        {"hs6": case["hs6"], "reporter_iso3": case["iso3"], "partner_iso3": p,
         "year": 2023, "flow": "M", "value_usd": v} for p, v in flows])
    pop = silk_seed_data.population(case["iso3"])          # حقيقي (لقطة WB)
    gpc = silk_seed_data.gdp_per_capita(case["iso3"])      # حقيقي (لقطة WB)
    if pop:
        silk_store.upsert_indicator(case["iso3"], "SP.POP.TOTL", int(pop[1]),
                                    pop[0], "World Bank (لقطة مضمّنة)", .9)
    if gpc:
        silk_store.upsert_indicator(case["iso3"], "NY.GDP.PCAP.CD", int(gpc[1]),
                                    gpc[0], "World Bank (لقطة مضمّنة)", .85)
    risk = {"CHN": (( -0.5, .6, 3.7)), "DEU": ((0.8, 1.6, 4.1))}[case["iso3"]]
    for ind, v in zip(("PV.EST", "RQ.EST", "LP.LPI.OVRL.XQ"), risk):
        silk_store.upsert_indicator(case["iso3"], ind, 2023, v,
                                    "World Bank", .95)
    for y in (2020, 2021, 2022, 2023):
        fx = {"CHN": 6.9 + (y - 2020) * 0.05, "DEU": 0.93}[case["iso3"]]
        silk_store.upsert_indicator(case["iso3"], "PA.NUS.FCRF", y, fx,
                                    "World Bank", .95)


class _HermeticHTTP:
    """بدائل HTTP واقعية الشكل — Serper/Maps/WB تعيد حمولات بنفس مخططات الإنتاج،
    مشتقة من نص الاستعلام نفسه (منتج+سوق) فيتباعد المحتوى طبيعياً."""

    def __init__(self):
        self.hits = {}

    def _resp(self, payload):
        m = mock.MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = payload
        m.status_code = 200
        return m

    def get(self, url, params=None, timeout=None, headers=None, **kw):
        self.hits.setdefault(url.split("/")[2], 0)
        self.hits[url.split("/")[2]] += 1
        q = (params or {}).get("query") or (params or {}).get("q") or ""
        if "wits" in url:
            # WITS غير مُبدَل عمداً — فشل معلن نظيف؛ مطابقة "worldbank" في
            # wits.worldbank.org كانت تعيد Mock فيتسرب MagicMock إلى ملاحظة
            # الفشل (إصلاح مراجعة Stage 5).
            raise OSError("hermetic: WITS not doubled — فجوة معلنة")
        if "maps.googleapis" in url:
            return self._resp({"status": "OK", "results": [
                {"name": f"موزّع {q[:18]} — نموذج A", "rating": 4.4,
                 "formatted_address": "Trade District 12"},
                {"name": f"مستورد {q[:18]} — نموذج B", "rating": 4.1,
                 "formatted_address": "Market St 7"}]})
        if "worldbank" in url:
            return self._resp([None, []])
        raise OSError("hermetic: host not doubled")

    def post(self, url, json=None, timeout=None, headers=None, **kw):
        self.hits.setdefault(url.split("/")[2], 0)
        self.hits[url.split("/")[2]] += 1
        q = (json or {}).get("q", "")
        if "serper" in url:
            return self._resp({"organic": [
                {"title": f"{q[:40]} — تقرير سوق 2024", "snippet":
                 f"معطيات مرصودة عن {q[:30]}", "link": "https://example.org/a"},
                {"title": f"دليل قنوات {q[:30]}", "snippet": "قنوات وتوزيع",
                 "link": "https://example.org/b"},
                {"title": f"مستوردون: {q[:30]}", "snippet": "قائمة مستوردين",
                 "link": "https://example.org/c"}]})
        raise OSError("hermetic: host not doubled")


def run_case(case, hermetic: bool):
    import silk_engine, silk_render
    if hermetic:
        os.environ["SILK_HERMETIC"] = "1"   # راية TEST RUN في كل المشتقات
        os.environ["SILK_STORE_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
        _seed_hermetic_store(case)
        os.environ.setdefault("SEARCH_API_KEY", "hermetic-double")
        os.environ.setdefault("GOOGLE_MAPS_API_KEY", "hermetic-double")
        dbl = _HermeticHTTP()
        import silk_trends_agent
        from silk_data_layer import DataPoint, _today
        interest = {"CHN": 72.0, "DEU": 34.0}[case["iso3"]]
        patches = [
            mock.patch("requests.get", dbl.get),
            mock.patch("requests.post", dbl.post),
            mock.patch("silk_data_layer._http_get",
                       side_effect=OSError("hermetic: live comtrade off")),
            mock.patch.object(
                silk_trends_agent, "trends_interest",
                lambda kw, geo=None, timeframe="today 12-m": DataPoint(
                    interest, "Google Trends", 0.7,
                    f"mean interest '{kw}' geo={geo} [hermetic double]",
                    _today())),
        ]
    else:
        patches = []
    ctx = patches and mock.patch.multiple  # noqa: F841 — clarity only
    for p in patches:
        p.start()
    try:
        res = silk_engine.analyze(case["product"],
                                  countries=[{"iso3": case["iso3"],
                                              "m49": case["m49"]}],
                                  year=2023, **POLICY)
    finally:
        for p in patches:
            p.stop()
    acc = {}
    _facts_by_source(res, acc)
    view = silk_render.build_view(res)
    return {
        "facts": {k: v[0] for k, v in sorted(acc.items()) if v[0] > 0},
        "gaps": {k: v[1] for k, v in sorted(acc.items()) if v[1] > 0},
        "coverage_pct": view["header"]["coverage_pct"],
        "text": silk_render.render_text(view),
        "sections_ok": [k for k, s in
                        view["markets"][0]["section_status"].items()
                        if s["status"] == "ok"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hermetic", action="store_true")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    hermetic = args.hermetic or not args.live

    out = {"mode": "hermetic" if hermetic else "live", "cases": {}}
    for case in CASES:
        out["cases"][case["name"]] = run_case(case, hermetic)

    a = out["cases"]["dates_CHN"]["text"].splitlines()
    b = out["cases"]["honey_DEU"]["text"].splitlines()
    sa, sb = set(a), set(b)
    ident = len(sa & sb)
    divergence_raw = round(100 - 100 * ident / max(1, len(sa | sb)), 1)

    def _content(lines):
        """أسطر المحتوى فقط: تحمل رقماً/نسبة/مصدراً — الإطار الثابت (═/عناوين
        مجردة) ليس «محتوى» يقاس عليه التشابه."""
        import re as _re
        return {l for l in lines
                if _re.search(r"[0-9٠-٩]|%|\$", l) and not set(l) <= {"═", " "}}

    ca, cb = _content(a), _content(b)
    ident_c = len(ca & cb)
    divergence = round(100 - 100 * ident_c / max(1, len(ca | cb)), 1)
    contrib = {}
    for src_label, needle in (("World Bank", "World Bank"),
                              ("Serper", "Serper"),
                              ("Google Maps", "Google Maps"),
                              ("Google Trends", "Google Trends")):
        contrib[src_label] = all(
            any(needle in k and n > 0 for k, n in
                out["cases"][c]["facts"].items())
            for c in ("dates_CHN", "honey_DEU"))
    out["metrics"] = {
        "identical_lines_raw": ident,
        "divergence_raw_pct": divergence_raw,
        "identical_content_lines": ident_c,
        "divergence_pct": divergence,
        "divergence_target_met": divergence >= 70.0,
        "four_sources_contribute": contrib,
        "all_sources_met": all(contrib.values()),
    }
    for c in out["cases"].values():
        c.pop("text")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

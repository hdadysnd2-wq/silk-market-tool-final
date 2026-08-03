"""اختبارات المرحلة ٢ — التثليث متعدد الإشارات (Serper/Maps/Trends) للفجوات
الرسمية (docs/SOURCE_AUDIT.md §7، مهمة #56). المطلوب حرفياً من التوجيه:

  ١) سيناريو تجويع كومتريد ⇐ تقدير مثلَّث (modeled:true + formula + sources
     + ثقة ≤0.5).
  ٢) سيناريو تجويع كل الإشارات ⇐ فجوة معلنة صادقة، بلا تقدير مختلق.

بالإضافة لاختبارات الدالة النقية `_triangulate_estimate` (أولوية الرقم
الرسمي، التعارض >30%، سقف الثقة) و`trends_series` (نداء واحد، مخرجان).
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

import silk_research as R  # noqa: E402
import silk_store  # noqa: E402
from silk_data_layer import DataPoint, _today  # noqa: E402

TASK = {"product": "دقيق قمح", "hs6": "110100", "iso3": "ARE", "m49": "784",
        "iso2": "AE", "market_name": "United Arab Emirates", "year": 2024}


def _dp(v, src="UN Comtrade (مخزن الحقائق)", conf=0.9, note=""):
    return DataPoint(v, src, conf, note, _today())


# ── _triangulate_estimate: الدالة النقية ─────────────────────────────────────

def test_triangulate_estimate_neither_available_is_gap():
    assert R._triangulate_estimate("x", None, None, [], "f", "n") is None


def test_triangulate_estimate_official_only_used_as_is_not_modeled():
    f = R._triangulate_estimate("import_growth_pct", _dp(12.0), None, [],
                                "f", "n", unit="%")
    assert f["value"] == 12.0 and f["modeled"] is False


def test_triangulate_estimate_estimate_only_modeled_and_capped_at_half():
    sources = [{"source": "Google Trends", "confidence": 0.7,
               "retrieved_at": _today(), "url": None}]
    f = R._triangulate_estimate("import_growth_pct", None, 22.5, sources,
                                "growth formula", "n=12", unit="%")
    assert f["value"] == 22.5 and f["modeled"] is True
    assert f["formula"] == "growth formula"
    assert f["sources"][0]["confidence"] == 0.5   # سقف 0.5، لا 0.7 الأصلية


def test_triangulate_estimate_conflict_over_30pct_official_wins_and_discloses():
    sources = [{"source": "Google Trends", "confidence": 0.7,
               "retrieved_at": _today(), "url": None}]
    f = R._triangulate_estimate("import_growth_pct", _dp(10.0), 20.0, sources,
                                "f", "n", unit="%")
    assert f["value"] == 10.0 and f["modeled"] is False   # الرسمي يفوز دوماً
    assert "تعارض" in f["note"] and "20.0" in f["note"]


def test_triangulate_estimate_agreement_under_30pct_discloses_no_conflict():
    sources = [{"source": "Google Trends", "confidence": 0.7,
               "retrieved_at": _today(), "url": None}]
    f = R._triangulate_estimate("import_growth_pct", _dp(10.0), 11.0, sources,
                                "f", "n", unit="%")
    assert f["value"] == 10.0
    assert "يتفق" in f["note"] and "تعارض" not in f["note"]


# ── trends_series: نداء واحد، مخرجان ──────────────────────────────────────────

def test_trends_series_no_pytrends_is_declared_none():
    import silk_trends_agent as T
    with block_network():
        out = T.trends_series("wheat flour", "AE")
    assert out["mean"] is None and out["growth_pct"] is None
    assert "n" in out and out["n"] == 0


# ── السيناريو ١ (مطلوب): تجويع كومتريد ⇐ تقدير مثلَّث ─────────────────────────

def test_starved_comtrade_produces_triangulated_estimate():
    silk_store.migrate()
    trend_sig = {"mean": 40.0, "growth_pct": 22.5, "n": 12, "confidence": 0.7,
                "note": "mean interest ... n=12"}
    places = [DataPoint({"name": f"Store {i}"}, "Google Maps", 0.7, "place",
                        _today()) for i in range(3)]
    with block_network(), \
         mock.patch("silk_research._trends_series", return_value=trend_sig), \
         mock.patch("silk_maps_agent.find_places", return_value=places):
        out = R.MarketSizeAgent().run(dict(TASK)).findings[0]
    by_metric = {f["metric"]: f for f in out["findings"]}
    assert "tam_usd" not in by_metric   # TAM يبقى فجوة — لا اختلاق دولار
    g = by_metric["import_growth_pct"]
    assert g["value"] == 22.5 and g["modeled"] is True and g["formula"]
    assert all(s["confidence"] <= 0.5 for s in g["sources"])
    idx = by_metric["market_activity_index"]
    assert idx["modeled"] is True and idx["formula"]
    assert 0.0 <= idx["value"] <= 1.0
    assert {s["source"] for s in idx["sources"]} == {"Google Maps",
                                                      "Google Trends"}
    assert any("tam_usd" in g_ for g_ in out["gaps"])


# ── السيناريو ٢ (مطلوب): تجويع كل الإشارات ⇐ فجوة صادقة ───────────────────────

def test_starved_everything_is_honest_gap_no_fabrication():
    silk_store.migrate()
    empty_trend = {"mean": None, "growth_pct": None, "n": 0, "confidence": 0.0,
                  "note": "pytrends unavailable / no network"}
    with block_network(), \
         mock.patch("silk_research._trends_series", return_value=empty_trend), \
         mock.patch("silk_maps_agent.find_places", return_value=[]):
        out = R.MarketSizeAgent().run(dict(TASK)).findings[0]
    assert out["status"] == "failed" and out["coverage"] == 0.0
    assert not any(f["value"] is not None for f in out["findings"])
    assert any("market_activity_index" in g and "لا بديل" in g
              for g in out["gaps"])
    assert any("import_growth_pct" in g for g in out["gaps"])


def test_market_pillar_falls_back_to_activity_index_when_tam_missing():
    import silk_decision as D
    bundle = {"market_attractiveness": {"tam_usd": None, "import_cagr_pct": None,
                                        "gdp_per_capita_usd": None,
                                        "saudi_share_pct": None,
                                        "market_activity_index": 0.6}}
    p = D._pillar_market(bundle["market_attractiveness"])
    assert p["value"] == 0.6 and "market_activity_index" not in p["missing"]
    assert "استُبدل" in p["basis"]
    # لا فرق ازدواج: عند وجود tam_usd الحقيقي، المؤشر البديل يُتجاهَل تماماً.
    bundle2 = {"market_attractiveness": {"tam_usd": 1e9, "import_cagr_pct": None,
                                         "gdp_per_capita_usd": None,
                                         "saudi_share_pct": None,
                                         "market_activity_index": 0.1}}
    p2 = D._pillar_market(bundle2["market_attractiveness"])
    assert p2["value"] == 1.0   # log10(1e9)/9 = 1.0 — المؤشر البديل لم يُستهلَك

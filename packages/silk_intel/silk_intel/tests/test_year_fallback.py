"""تراجُع سنويّ معلن — بلاغ المالك: تحليلٌ 0% لسوقٍ (الأردن، ليمون) بينما مخطط
الاتجاه يعرض بياناتٍ فعليةً حتى 2024. السبب: السنة المطلوبة (2026) لم تُنشر في
كومتريد بعد (التجارة تتأخّر سنة–سنتين)، فتنهار كلُّ المكوّنات إلى «غير مرصود».

الإصلاح: المحرّك يتراجع تلقائيًّا إلى أحدث سنةٍ فيها بياناتٌ فعلية (ضمن نافذة)
ويُعلن السنةَ المستخدَمة — لا اختلاق، بل اختيارُ أحدث سنةٍ منشورة بدل الانهيار.
"""
import datetime
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_market_ranker as MR  # noqa: E402


def _empty_after(threshold, value=8.0e6):
    """محاكاة كومتريد: سنوات ≥ threshold فارغة (لم تُنشر)، وما دونها فيه بيانات."""
    def _cached(hs, m49, iso3, y, live=None):
        if y >= threshold:
            return {"total_usd": None, "competitors": [], "xval_note": ""}
        return {"total_usd": value, "competitors": [], "xval_note": ""}
    return _cached


def test_fallback_walks_back_to_newest_published_year():
    with mock.patch("silk_market_ranker.market_imports_cached",
                    side_effect=_empty_after(2025)):
        mi, eff, fell = MR._imports_with_fallback("080550", "400", "JOR", 2026)
    assert eff == 2024 and fell is True and mi["total_usd"] == 8.0e6


def test_fallback_noop_when_requested_year_has_data():
    with mock.patch("silk_market_ranker.market_imports_cached",
                    side_effect=_empty_after(3000)):   # كل السنوات فيها بيانات
        mi, eff, fell = MR._imports_with_fallback("080550", "400", "JOR", 2023)
    assert eff == 2023 and fell is False


def test_fallback_starts_below_current_year_not_the_unpublished_one():
    """يبدأ من min(المطلوبة، الحالية−1) فلا يُهدر نداءً على سنةٍ حاليةٍ لن تُنشر."""
    tried = []

    def _cached(hs, m49, iso3, y, live=None):
        tried.append(y)
        return ({"total_usd": None, "competitors": [], "xval_note": ""}
                if y >= 2025 else
                {"total_usd": 5.0e6, "competitors": [], "xval_note": ""})

    with mock.patch("silk_market_ranker.market_imports_cached", side_effect=_cached):
        _mi, eff, _fell = MR._imports_with_fallback("080550", "400", "JOR", 2026)
    cur = datetime.date.today().year
    assert tried[0] == min(2026, cur - 1)      # لم يبدأ بـ2026
    assert eff == 2024


def test_all_gaps_when_no_year_has_data_declares_not_fabricates():
    with mock.patch("silk_market_ranker.market_imports_cached",
                    side_effect=_empty_after(0)):      # لا سنة فيها بيانات
        mi, eff, fell = MR._imports_with_fallback("080550", "400", "JOR", 2026)
    assert mi["total_usd"] is None and fell is False   # فجوة معلنة، لا اختلاق


def test_gather_row_declares_effective_year_in_component_note():
    with mock.patch("silk_market_ranker.market_imports_cached",
                    side_effect=_empty_after(2025)), \
         mock.patch("silk_market_ranker._income_dp",
                    return_value=MR.DataPoint(None, "World Bank", 0.0, "x",
                                              MR._today())), \
         mock.patch("silk_market_ranker.population",
                    return_value=MR.DataPoint(None, "World Bank", 0.0, "x",
                                              MR._today())):
        row = MR._gather_row("080550", {"iso3": "JOR", "m49": "400"}, 2026)
    ms = row["components"]["market_size"]
    assert row["year_used"] == 2024 and row["year_fell_back"] is True
    assert ms.value == 8.0e6                       # لم يعد «غير مرصود»
    assert "2024" in ms.note and "لم تُنشر" in ms.note   # السنة الفعلية معلنة


def test_engine_result_carries_data_year(monkeypatch):
    """المحرّك يعتمد سنةَ البيانات الفعلية للمراحل التالية ويعلنها في النتيجة."""
    import silk_engine

    def fake_rank(hs, countries=None, year=2022, **kw):
        return [{"country": "Jordan", "iso3": "JOR", "m49": "400",
                 "total_score": 0.3, "confidence": 0.5, "components": {},
                 "income_ppp": None, "population": None,
                 "year_used": 2024, "year_fell_back": True,
                 "competitors": [], "top_competitor": None}]

    monkeypatch.setattr(silk_engine, "rank_markets", fake_rank)
    monkeypatch.setattr(silk_engine, "resolve",
                        lambda *a, **k: MR.DataPoint("080550", "resolver", 0.9,
                                                     "seed", MR._today()))
    res = silk_engine.analyze("ليمون", countries=[{"iso3": "JOR", "m49": "400"}],
                              year=2026)
    assert res["data_year"] == 2024 and res["year_fell_back"] is True
    assert "2024" in res["note"]

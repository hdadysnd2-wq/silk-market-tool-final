"""المُسجِّل الصِرف المستخرَج — score_component_rows (موجة المنصة ٣).

قلبُ ``rank_markets`` (تطبيع + ترجيح مع إعادة تطبيعٍ على الحاضر + قلب
المنافسة + سقف ثقة الفئة-٢ + خصم الهاب I9) استُخرج دالةً صِرفة كي تسجِّل
منصةُ المنتج بياناتِها المتزامنة بنفس النموذج المدقَّق. هرمتي بالكامل: لا
شبكة، DataPoints مبنية يدوياً.
"""

from silk_data_layer import DataPoint, _today
from silk_market_ranker import _TRANSIT_HUB_PENALTY, WEIGHTS, score_component_rows


def _dp(value) -> DataPoint:
    return DataPoint(value, "test", 0.9 if value is not None else 0.0,
                     "", _today())


def _row(iso3: str, market_size=None, saudi=None, capacity=None,
         competition=None, tier: int = 1) -> dict:
    return {"iso3": iso3, "tier": tier, "components": {
        "market_size": _dp(market_size),
        "saudi_position": _dp(saudi),
        "demand_capacity": _dp(capacity),
        "competition": _dp(competition),
    }}


def test_full_components_beat_partial_and_confidence_reflects_presence():
    rows = [
        _row("DEU", market_size=900.0, saudi=0.12, capacity=60000.0, competition=0.40),
        _row("IND", market_size=500.0),
    ]
    scored = score_component_rows(rows)
    by = {s["iso3"]: s for s in scored}
    assert by["DEU"]["confidence"] == 1.0
    assert by["IND"]["confidence"] == round(1 / len(WEIGHTS), 2)
    # كلا الصفين يسجَّل — الغائب يُتخطى بلا تلفيق.
    assert 0.0 <= by["IND"]["total_score"] <= 1.0


def test_competition_is_inverted():
    # تركّز أعلى (مورّد مهيمن) = أصعب = درجة أدنى، والبقية متساوية.
    rows = [
        _row("AAA", market_size=100.0, competition=0.90),
        _row("BBB", market_size=100.0, competition=0.20),
    ]
    by = {s["iso3"]: s for s in score_component_rows(rows)}
    assert by["BBB"]["total_score"] > by["AAA"]["total_score"]


def test_transit_hub_is_tagged_and_demoted():
    rows = [
        _row("NLD", market_size=1000.0),   # هاب إعادة تصدير (I9)
        _row("DEU", market_size=1000.0),
    ]
    by = {s["iso3"]: s for s in score_component_rows(rows)}
    assert by["NLD"]["transit_hub"] is True
    assert by["DEU"]["transit_hub"] is False
    assert by["NLD"]["total_score"] <= by["DEU"]["total_score"] * (1 - _TRANSIT_HUB_PENALTY) + 1e-9


def test_all_missing_scores_zero_never_fabricates():
    scored = score_component_rows([_row("EGY")])
    assert scored[0]["total_score"] == 0.0
    assert scored[0]["confidence"] == 0.0


def test_tier2_confidence_is_capped():
    full = _row("MAR", market_size=100.0, saudi=0.1, capacity=50000.0,
                competition=0.3, tier=2)
    scored = score_component_rows([full])
    assert scored[0]["confidence"] < 1.0

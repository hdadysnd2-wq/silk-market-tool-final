"""المُسجِّل الصِرف المستخرَج — score_component_rows (موجة المنصة ٣ + J1).

قلبُ ``rank_markets`` (تطبيع + ترجيح مع إعادة تطبيعٍ على الحاضر + قلب
المكوّنات المعكوسة + سقف ثقة الفئة-٢ + خصم الهاب I9) استُخرج دالةً صِرفة كي
تسجِّل منصةُ المنتج بياناتِها المتزامنة بنفس النموذج المدقَّق. J1 وسّع النموذج
إلى سبعة مكوّنات (نموذج واحد، لا مُسجِّل موازٍ): سعر الوحدة غير معكوس (هامش
سعري أعلى = أفضل)، والرسوم والمسافة معكوستان (أقل = أفضل). هرمتي بالكامل: لا
شبكة، DataPoints مبنية يدوياً.
"""

from silk_data_layer import DataPoint, _today
from silk_market_ranker import (
    _INVERTED_COMPONENTS,
    _TRANSIT_HUB_PENALTY,
    WEIGHTS,
    score_component_rows,
)


def _dp(value) -> DataPoint:
    return DataPoint(value, "test", 0.9 if value is not None else 0.0,
                     "", _today())


def _row(iso3: str, market_size=None, saudi=None, capacity=None,
         competition=None, unit_price=None, tariff=None, distance=None,
         tier: int = 1) -> dict:
    return {"iso3": iso3, "tier": tier, "components": {
        "market_size": _dp(market_size),
        "saudi_position": _dp(saudi),
        "demand_capacity": _dp(capacity),
        "competition": _dp(competition),
        "unit_price_level": _dp(unit_price),
        "tariff_access": _dp(tariff),
        "logistics_proximity": _dp(distance),
    }}


def _full_row(iso3: str, **overrides) -> dict:
    base = dict(market_size=900.0, saudi=12.0, capacity=60000.0,
                competition=0.40, unit_price=2.5, tariff=0.05, distance=4000.0)
    base.update(overrides)
    return _row(iso3, **base)


def test_weights_are_the_owners_seven_and_sum_to_one():
    # J1 — the locked seven-component table (owner's order); exactly ONE model.
    assert list(WEIGHTS.items()) == [
        ("market_size", 0.30),
        ("demand_capacity", 0.20),
        ("saudi_position", 0.15),
        ("unit_price_level", 0.10),
        ("tariff_access", 0.10),
        ("competition", 0.10),
        ("logistics_proximity", 0.05),
    ]
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    # Inversion semantics: lower tariff / concentration / distance = better;
    # unit price is deliberately NOT inverted (higher = price headroom).
    assert _INVERTED_COMPONENTS == {"competition", "tariff_access",
                                    "logistics_proximity"}


def test_full_components_beat_partial_and_confidence_reflects_presence():
    rows = [
        _full_row("DEU"),
        _row("IND", market_size=500.0),
    ]
    scored = score_component_rows(rows)
    by = {s["iso3"]: s for s in scored}
    assert by["DEU"]["confidence"] == 1.0
    assert by["IND"]["confidence"] == round(1 / len(WEIGHTS), 2)
    # كلا الصفين يسجَّل — الغائب يُتخطى بلا تلفيق.
    assert 0.0 <= by["IND"]["total_score"] <= 1.0


def test_missing_components_renormalize_over_present_weights():
    # صفٌّ بمكوّنين حاضرين فقط، كلاهما الأفضل في فئته => درجة كاملة بعد إعادة
    # التطبيع (0.30+0.20 يعاد تطبيعهما إلى 1.0)، والثقة تعلن النقص 2/7.
    rows = [
        _row("AAA", market_size=900.0, capacity=60000.0),
        _row("BBB", market_size=100.0, capacity=10000.0),
    ]
    by = {s["iso3"]: s for s in score_component_rows(rows)}
    assert by["AAA"]["total_score"] == 1.0
    assert by["AAA"]["confidence"] == round(2 / len(WEIGHTS), 2)


def test_competition_is_inverted():
    # تركّز أعلى (مورّد مهيمن) = أصعب = درجة أدنى، والبقية متساوية.
    rows = [
        _row("AAA", market_size=100.0, competition=0.90),
        _row("BBB", market_size=100.0, competition=0.20),
    ]
    by = {s["iso3"]: s for s in score_component_rows(rows)}
    assert by["BBB"]["total_score"] > by["AAA"]["total_score"]


def test_tariff_access_is_inverted_lower_tariff_wins():
    # J1 — رسوم مطبقة أدنى = وصول أسهل = درجة أعلى، والبقية متساوية.
    rows = [
        _row("AAA", market_size=100.0, tariff=0.15),
        _row("BBB", market_size=100.0, tariff=0.02),
    ]
    by = {s["iso3"]: s for s in score_component_rows(rows)}
    assert by["BBB"]["total_score"] > by["AAA"]["total_score"]


def test_logistics_proximity_is_inverted_fewer_km_wins():
    # J1 — مسافة أقصر من جدة = أفضل، والبقية متساوية.
    rows = [
        _row("AAA", market_size=100.0, distance=12000.0),
        _row("BBB", market_size=100.0, distance=1500.0),
    ]
    by = {s["iso3"]: s for s in score_component_rows(rows)}
    assert by["BBB"]["total_score"] > by["AAA"]["total_score"]


def test_unit_price_level_is_not_inverted_higher_unit_value_wins():
    # J1 — قيمة وحدة مرصودة أعلى = هامش سعري أكبر = درجة أعلى (لا قلب).
    rows = [
        _row("AAA", market_size=100.0, unit_price=1.10),
        _row("BBB", market_size=100.0, unit_price=6.40),
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
    full = _full_row("MAR", tier=2)
    scored = score_component_rows([full])
    assert scored[0]["confidence"] < 1.0

"""Relevance scoring — pure function, table-driven."""

from __future__ import annotations

from app.providers.base import SourceType
from app.services.scoring import WEIGHTS, ScoringInput, score_buyer


def _base(**overrides) -> ScoringInput:
    defaults = {
        "product_hs_code": "392010",
        "buyer_hs_codes": ["392010"],
        "shipment_count_12m": 12,
        "total_value_usd_12m": 500_000,
        "days_since_last_shipment": 30,
        "buyer_country_iso2": "IN",
        "employee_count": 150,
        "source": SourceType.CUSTOMS,
    }
    defaults.update(overrides)
    return ScoringInput(**defaults)


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_strong_buyer_scores_high():
    assert score_buyer(_base()).total >= 80


def test_weak_buyer_scores_low():
    weak = _base(
        buyer_hs_codes=["847130"],
        shipment_count_12m=0,
        total_value_usd_12m=0,
        days_since_last_shipment=None,
        buyer_country_iso2="US",
        employee_count=3,
        source=SourceType.MAPS,
    )
    assert score_buyer(weak).total <= 30


def test_hs6_beats_hs4_beats_hs2():
    hs6 = score_buyer(_base(buyer_hs_codes=["392010"])).factors["hs_match"]["points"]
    hs4 = score_buyer(_base(buyer_hs_codes=["392099"])).factors["hs_match"]["points"]
    hs2 = score_buyer(_base(buyer_hs_codes=["391000"])).factors["hs_match"]["points"]
    assert hs6 > hs4 > hs2


def test_source_quality_customs_beats_maps():
    customs = score_buyer(_base(source=SourceType.CUSTOMS)).factors["source_quality"]["points"]
    maps = score_buyer(_base(source=SourceType.MAPS)).factors["source_quality"]["points"]
    assert customs > maps


def test_breakdown_points_sum_to_total():
    breakdown = score_buyer(_base())
    summed = round(sum(f["points"] for f in breakdown.factors.values()))
    assert abs(summed - breakdown.total) <= 1


def test_score_bounded_0_100():
    result = score_buyer(_base(shipment_count_12m=1000, total_value_usd_12m=10**9))
    assert 0 <= result.total <= 100

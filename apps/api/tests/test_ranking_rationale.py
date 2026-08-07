"""J1 — the deterministic one-line ranking rationale (transparent scoring).

Pure-function locks: the rationale names the TOP TWO present components by the
engine's real model weights, formats their persisted values sanely, carries
their sources, exists in BOTH EN and AR, and never invents a number — an empty
component dict yields ``None`` (a declared absence), not a filler sentence.
"""

from __future__ import annotations

import re

from app.services.ranking_rationale import build_rationale


def _components() -> dict[str, dict]:
    return {
        "market_size": {"value": 1_250_000.0, "source": "world_trade", "note": ""},
        "demand_capacity": {"value": 45_000.0, "source": "worldbank", "note": ""},
        "logistics_proximity": {
            "value": 4337.0,
            "source": "haversine(Jeddah→main port)",
            "note": "",
        },
    }


def test_rationale_names_the_two_heaviest_components_with_values_and_sources():
    r = build_rationale(_components())
    assert r is not None
    # market_size (.30) and demand_capacity (.20) outweigh logistics (.05).
    assert "market size" in r["en"] and "demand capacity" in r["en"]
    assert "distance" not in r["en"]
    # Real values, sanely formatted, with their sources in parentheses.
    assert "$1.2M" in r["en"] and "(world_trade)" in r["en"]
    assert "$45.0K" in r["en"] and "(worldbank)" in r["en"]
    # AR mirror names the same components and the same figures.
    assert "حجم السوق" in r["ar"] and "طاقة الطلب" in r["ar"]
    assert "$1.2M" in r["ar"] and "(world_trade)" in r["ar"]


def test_rationale_uses_only_present_components_no_invented_numbers():
    # Only one component present → the line names exactly that one; every digit
    # in the output traces to the persisted value (nothing invented, I1).
    r = build_rationale({"tariff_access": {"value": 0.05, "source": "wits", "note": ""}})
    assert r is not None
    assert "applied tariff 5.0% (wits)" in r["en"]
    assert "الرسوم الجمركية المطبقة" in r["ar"]
    # No other component name leaks in.
    assert "market size" not in r["en"]
    numbers = set(re.findall(r"\d+\.?\d*", r["en"]))
    assert numbers == {"5.0"}


def test_rationale_is_deterministic():
    assert build_rationale(_components()) == build_rationale(_components())


def test_rationale_declares_absence_on_no_components():
    assert build_rationale(None) is None
    assert build_rationale({}) is None
    # Components whose value is a declared gap (None) cannot be contributors.
    assert build_rationale({"market_size": {"value": None, "source": "x"}}) is None


def test_rationale_formats_each_component_unit_sanely():
    r = build_rationale(
        {
            "unit_price_level": {"value": 2.3456, "source": "world_trade"},
            "logistics_proximity": {"value": 4337.0, "source": "haversine(Jeddah→main port)"},
        }
    )
    assert r is not None
    assert "$2.35/unit" in r["en"]
    assert "4,337 km" in r["en"]

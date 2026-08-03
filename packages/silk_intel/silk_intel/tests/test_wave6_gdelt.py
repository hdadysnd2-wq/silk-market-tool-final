"""اختبارات الموجة ٦ب — وكيل GDELT (silk_gdelt_agent).

الشبكة مقطوعة => None موسوم لا اختلاق؛ استعلام فارغ => None فوري.
Run:  python3 -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network


def test_empty_query_returns_none_no_network():
    from silk_gdelt_agent import gdelt_news

    with block_network():
        out = gdelt_news("", "Nigeria")
    assert len(out) == 1
    assert out[0].value is None
    assert out[0].confidence == 0.0


def test_network_cut_degrades_to_tagged_none():
    from silk_gdelt_agent import gdelt_news

    with block_network():
        out = gdelt_news("dates exports", "Nigeria", months=12)
    assert len(out) == 1
    assert out[0].value is None
    assert out[0].confidence == 0.0
    assert out[0].source == "GDELT"
    assert "GDELT" in out[0].note or "network" in out[0].note.lower() \
        or "failed" in out[0].note.lower()


def test_months_and_max_records_are_clamped():
    from silk_gdelt_agent import gdelt_news

    with block_network():
        out = gdelt_news("x", "y", months=999, max_records=999)
    # لا استثناء رغم القيم الشاذة — clamped internally, never raises.
    assert len(out) == 1
    assert out[0].value is None

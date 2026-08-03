"""اختبارات الموجة ٦أ — مُحلِّل السوق العالمي (silk_market_resolver).

يغطي: مطابقة تامة (عربي/إنجليزي/ISO3)، مطابقة تقريبية، مطابقة ضعيفة تعيد
None + اقتراحات (لا تخمين صامت)، وشكل data/countries.csv نفسه.
Run:  python3 -m pytest tests/ -q
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "countries.csv")


def test_exact_match_english_arabic_iso3():
    from silk_market_resolver import resolve_market

    for q in ("nigeria", "نيجيريا", "NGA", "Nigeria"):
        ref, suggestions = resolve_market(q)
        assert ref is not None, q
        assert ref.iso3 == "NGA"
        assert ref.m49 == "566"
        assert suggestions == []


def test_abbreviated_forms_with_periods_resolve():
    # نموذج انحدار: "U.A.E."/"U.K."/"U.S.A." كانت تسقط دون النقاط.
    from silk_market_resolver import resolve_market

    for q, expected in (("U.A.E.", "ARE"), ("U.K.", "GBR"), ("U.S.A.", "USA"),
                       ("Turkey", "TUR")):
        ref, _ = resolve_market(q)
        assert ref is not None, q
        assert ref.iso3 == expected


def test_weak_match_returns_none_and_suggestions():
    from silk_market_resolver import resolve_market

    ref, suggestions = resolve_market("Nigera")  # typo, ambiguous w/ Niger
    assert ref is None
    assert "Nigeria" in suggestions
    assert len(suggestions) <= 5


def test_no_match_never_guesses():
    from silk_market_resolver import resolve_market

    ref, suggestions = resolve_market("xyzabc123notacountry")
    assert ref is None
    assert isinstance(suggestions, list)


def test_empty_query_returns_none():
    from silk_market_resolver import resolve_market

    ref, suggestions = resolve_market("")
    assert ref is None
    assert suggestions == []


def test_countries_csv_shape_and_real_codes():
    rows = list(csv.DictReader(open(_CSV, encoding="utf-8")))
    assert len(rows) > 200
    for col in ("iso3", "iso2", "m49", "name_en", "name_ar", "aliases",
               "region", "source_url"):
        assert col in rows[0]
    by_iso3 = {r["iso3"]: r for r in rows}
    # رموز حقيقية معروفة — real, verifiable codes (not invented).
    assert by_iso3["SAU"]["m49"] == "682"
    assert by_iso3["EGY"]["m49"] == "818"
    assert by_iso3["CHN"]["m49"] == "156"
    for iso3, r in by_iso3.items():
        assert r["name_ar"], f"{iso3} missing an Arabic name"
        assert r["source_url"], f"{iso3} missing a source citation"

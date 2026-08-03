"""اختبارات الموجة ٦د — مراجع L1 الجديدة (ديموغرافيا/موانئ/اتفاقيات).

شكل الملفات + استشهاد كل صف بمصدره + تغطية أسواق سِلك الـ٣٨ ذات الأولوية
(silk_market_ranker.COUNTRIES) — لا اختلاق، لا صف بلا مصدر.
Run:  python3 -m pytest tests/ -q
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _rows(fname: str) -> list[dict]:
    with open(os.path.join(_DATA, fname), encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return list(csv.DictReader(lines))


def _priority_iso3() -> set[str]:
    from silk_market_ranker import COUNTRIES
    return {c["iso3"] for c in COUNTRIES}


def test_demographics_l1_shape_and_citations():
    rows = _rows("demographics_l1.csv")
    assert len(rows) > 200
    for col in ("iso3", "name_en", "population", "muslim_pct",
               "muslim_pct_source", "note"):
        assert col in rows[0]
    for r in rows:
        if r["muslim_pct"]:
            assert r["muslim_pct_source"], f"{r['iso3']} muslim_pct w/o source"
        if not r["population"] and not r["muslim_pct"]:
            assert r["note"], f"{r['iso3']} fully empty but no declared gap"


def test_demographics_l1_covers_priority_markets():
    rows = {r["iso3"]: r for r in _rows("demographics_l1.csv")}
    for iso3 in _priority_iso3():
        assert iso3 in rows, iso3
        assert rows[iso3]["population"], f"{iso3} missing population"


def test_ports_l1_shape_and_citations():
    rows = _rows("ports_l1.csv")
    assert len(rows) > 150
    for r in rows:
        assert r["main_port"], r["iso3"]
        assert r["source"], f"{r['iso3']} port w/o source"
        assert r["port_type"] in ("sea", "landlocked_corridor")


def test_ports_l1_covers_priority_markets():
    rows = {r["iso3"]: r for r in _rows("ports_l1.csv")}
    missing = _priority_iso3() - set(rows)
    assert not missing, f"priority markets missing a port: {missing}"


def test_agreements_l1_shape_and_citations():
    rows = _rows("agreements_l1.csv")
    assert rows
    for r in rows:
        assert r["agreement"]
        assert r["status"] in ("member", "in_accession")
        assert r["source_url"], f"{r['iso3']}/{r['agreement']} w/o source_url"


def test_agreements_l1_gcc_members_are_correct():
    rows = _rows("agreements_l1.csv")
    gcc_markets = {r["iso3"] for r in rows if r["agreement"] == "GCC"}
    assert gcc_markets == {"ARE", "QAT", "KWT", "OMN", "BHR"}


def test_agreements_l1_known_wto_non_members_not_asserted_as_members():
    # لبنان والجزائر وإثيوبيا في مسار انضمام WTO لا أعضاء كاملون — لا يجوز
    # عرضها "member" (اختبار انحدار ضد افتراض تلقائي خاطئ).
    rows = _rows("agreements_l1.csv")
    wto = {r["iso3"]: r["status"] for r in rows if r["agreement"] == "WTO"}
    for iso3 in ("LBN", "DZA", "ETH"):
        assert wto.get(iso3) == "in_accession", (iso3, wto.get(iso3))

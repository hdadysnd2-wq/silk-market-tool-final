"""C2–C5 (SPEC-v2, Command #5b) — تكامل مكشطة الخرائط: استعلامات مُوطَّنة،
تقديم/استطلاع، تحليل + إزالة تكرار + أعلى ١٥، تخزين مؤقت، السلسلة
الاحتياطية (Places)، مضاهاة مرشّحي الويب، وعقد عدم الاختلاق (فجوة معلنة).

HTTP مموّه بالكامل — لا شبكة. تكامل الأنابيب الحيّ يتحقّق منه المالك على
Railway (الخدمة على شبكة خاصة غير قابلة للوصول من بيئة الاختبار).

Run: python3 -m pytest tests/test_gmaps_integration_c2345.py -q
"""
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_NLD = SimpleNamespace(iso3="NLD", iso2="NL", m49=528,
                       name_en="Netherlands", name_ar="هولندا")


@pytest.fixture(autouse=True)
def _isolated_leads_cache(monkeypatch):
    """عزل مخزن الروابط لكل اختبار — لا تلوّث ترتيبي بين الاختبارات."""
    monkeypatch.setenv("SILK_CACHE_DIR", tempfile.mkdtemp())


def _resp(json_body, ok=True):
    return SimpleNamespace(
        ok=ok, json=lambda: json_body,
        raise_for_status=lambda: None if ok else (_ for _ in ()).throw(
            OSError("http error")))


def test_localized_queries_dutch_dates():
    import silk_gmaps
    qs = silk_gmaps.localized_queries("تمور", _NLD)
    assert len(qs) == 4
    joined = " | ".join(qs)
    assert "dadels" in joined            # المنتج مُوطَّن للهولندية
    assert "groothandel" in joined       # جملة
    assert "halal groothandel" in joined
    assert "arabische supermarkt groothandel" in qs


def test_submit_scrape_returns_id_then_none_on_failure():
    import silk_gmaps
    with patch.dict(os.environ, {"SILK_GMAPS_SCRAPER_URL": "http://s:8080"}):
        with patch("requests.post", return_value=_resp({"id": "job-1"})):
            assert silk_gmaps.submit_scrape(["q1", "q2"]) == "job-1"
        with patch("requests.post", side_effect=OSError("down")):
            assert silk_gmaps.submit_scrape(["q1"]) is None
    # معطّلة (بلا URL) => None بلا محاولة
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SILK_GMAPS_SCRAPER_URL", None)
        assert silk_gmaps.submit_scrape(["q1"]) is None


def test_parse_and_rank_dedupes_parses_and_caps_15():
    import silk_gmaps
    raw = [
        {"title": "Ajwa XL", "address": "Rotterdam 1", "phone": "+3110",
         "emails": ["sales@ajwa.nl"], "website": "ajwa.nl", "rating": 4.5,
         "reviews": 120, "link": "https://maps.google/ajwa"},
        {"name": "Ajwa XL", "full_address": "Rotterdam 1"},  # تكرار أفقر
    ] + [{"title": f"Co {i}", "address": f"A{i}", "phone": f"p{i}"}
         for i in range(20)]
    out = silk_gmaps.parse_and_rank(raw)
    assert len(out) == 15                       # أعلى ١٥
    ajwa = [l for l in out if l["name"] == "Ajwa XL"]
    assert len(ajwa) == 1                        # تكرار مُزال
    assert ajwa[0]["email"] == "sales@ajwa.nl"   # الأغنى بقي
    assert ajwa[0]["phone"] == "+3110"
    assert ajwa[0]["maps_link"] == "https://maps.google/ajwa"
    assert ajwa[0]["doc_level"] == silk_gmaps._MAPS_DOC_LEVEL


def test_parse_never_fabricates_missing_fields():
    import silk_gmaps
    out = silk_gmaps.parse_and_rank([{"title": "X only"}])
    assert out[0]["email"] == "" and out[0]["phone"] == ""   # غائب = '' لا اختلاق
    assert out[0]["rating"] is None


def test_leads_cache_roundtrip_reused_across_runs():
    import silk_gmaps
    qs = ["dadels groothandel"]
    leads = [{"name": "Ajwa XL", "email": "x@y.nl"}]
    silk_gmaps.cache_put("NLD", qs, leads)
    assert silk_gmaps.cache_get("NLD", qs) == leads
    assert silk_gmaps.cache_get("DEU", qs) is None   # مفتاح السوق يفصل


def test_places_fallback_gives_name_address_rating_no_email():
    import silk_gmaps
    from silk_data_layer import DataPoint
    fake = [DataPoint({"name": "Halal Groothandel BV", "address": "Amsterdam",
                       "rating": 4.2, "user_ratings_total": 30}, "Google Maps",
                      0.7, "place")]
    with patch("silk_maps_agent.find_places", return_value=fake):
        rows = silk_gmaps.places_fallback("dadels", _NLD)
    assert rows and rows[0]["name"] == "Halal Groothandel BV"
    assert rows[0]["email"] == ""                    # Places بلا إيميل (C4)
    assert rows[0]["rating"] == 4.2
    assert rows[0]["doc_level"] == silk_gmaps._MAPS_DOC_LEVEL


def test_web_candidates_cross_matched_and_merged():
    import silk_gmaps
    leads = [{"name": "Ajwa XL", "address": "R", "phone": "p", "email": "e",
              "doc_level": silk_gmaps._MAPS_DOC_LEVEL}]
    merged = silk_gmaps._merge_web_candidates(leads, ["Ajwa XL", "NutsWorld",
                                                       "All4Trade"])
    names = [m["name"] for m in merged]
    assert names.count("Ajwa XL") == 1               # مطابق => لا تكرار
    assert "NutsWorld" in names and "All4Trade" in names
    web_rows = [m for m in merged if m["name"] == "NutsWorld"]
    assert web_rows[0]["doc_level"] == silk_gmaps._WEB_DOC_LEVEL
    assert web_rows[0]["email"] == ""                # مرشّح ويب: اسم فقط


def test_finalize_scraper_path_when_future_returns_results():
    import silk_gmaps
    from concurrent.futures import ThreadPoolExecutor
    raw = [{"title": "Ajwa XL", "phone": "+3110", "emails": ["s@ajwa.nl"]}]
    fut = ThreadPoolExecutor(max_workers=1).submit(lambda: raw)
    with patch.dict(os.environ, {"SILK_GMAPS_SCRAPER_URL": "http://s:8080"}):
        out = silk_gmaps.finalize_leads(fut, "تمور", _NLD, timeout_s=5)
    assert out["path"] == "scraper"
    assert out["leads"][0]["name"] == "Ajwa XL"


def test_finalize_falls_back_to_places_when_scraper_empty():
    import silk_gmaps
    from concurrent.futures import ThreadPoolExecutor
    from silk_data_layer import DataPoint
    fut = ThreadPoolExecutor(max_workers=1).submit(lambda: [])   # كشط فارغ
    fake = [DataPoint({"name": "Halal BV", "address": "A"}, "Google Maps", .7, "p")]
    with patch("silk_maps_agent.find_places", return_value=fake):
        out = silk_gmaps.finalize_leads(fut, "dadels", _NLD, timeout_s=5)
    assert out["path"] == "places"
    assert out["leads"][0]["name"] == "Halal BV"


def test_finalize_declared_gap_when_both_fail_no_fabrication():
    import silk_gmaps
    from concurrent.futures import ThreadPoolExecutor
    fut = ThreadPoolExecutor(max_workers=1).submit(lambda: None)  # كشط سقط
    with patch("silk_maps_agent.find_places", return_value=[]):   # Places سقط
        out = silk_gmaps.finalize_leads(fut, "dadels", _NLD, timeout_s=5)
    assert out["path"] == "gap"
    assert out["leads"] == []                        # فجوة معلنة، لا صف مختلَق


def test_finalize_none_future_disabled_is_gap_not_crash():
    import silk_gmaps
    with patch("silk_maps_agent.find_places", return_value=[]):
        out = silk_gmaps.finalize_leads(None, "dadels", _NLD, timeout_s=1)
    assert out["path"] == "gap" and out["leads"] == []

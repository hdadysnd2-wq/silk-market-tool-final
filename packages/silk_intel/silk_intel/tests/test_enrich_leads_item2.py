"""البند ٢ (بلاغ UK الحي، أمر العمل الرئيس) — مسار تعبئة روابط المستوردين
الرخيص لبحث محفوظ: `POST /analyses/{id}/enrich-leads`.

المكشطة نُشرت متأخّراً (SILK_GMAPS_SCRAPER_URL ضُبط بعد إنجاز تقارير)، فتقرير
المالك القائم يحمل «فجوة معلنة» في جدول المستوردين. هذه النقطة تكشط الخرائط
للسوق/المنتج المخزَّنَين وتحدّث `importer_leads` بلا أيّ نداء كلود ولا إعادة
تشغيل البعثات — قروش بدل ~3$ لإعادة تشغيل كاملة.

يغطّي: التعطيل النظيف (مكشطة غائبة)، 404/400، صفر نداء كلود، الحفظ عند نجاح
الكشط، وعدم طمس روابط قائمة بفجوة عند فشل الكشط.

Run: python3 -m pytest tests/test_enrich_leads_item2.py -q
"""
import contextlib
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@contextlib.contextmanager
def _env(**vals):
    saved = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _client():
    from fastapi.testclient import TestClient
    import api
    import importlib
    importlib.reload(api)
    return TestClient(api.app)


def _boom(*a, **k):
    raise AssertionError("Claude must never be called by /enrich-leads")


@contextlib.contextmanager
def _no_claude():
    with patch("silk_llm_provider.AnthropicProvider.complete", side_effect=_boom), \
         patch("silk_llm_provider.AnthropicProvider.complete_tools",
               side_effect=_boom):
        yield


def _seed_research(db: str) -> int:
    import silk_storage as ST
    from canonical_netherlands import netherlands_research_blob
    return ST.save_analysis(netherlands_research_blob(), path=db)


def _seed_analyze(db: str) -> int:
    """نتيجة /analyze كلاسيكية (بلا deep_research) — لاختبار الرفض 400."""
    import silk_storage as ST
    return ST.save_analysis({
        "product": "تمور", "hs_code": "080410", "markets": [
            {"country": "NLD", "total_score": 0.5}]}, path=db)


def test_enrich_leads_clean_disable_when_scraper_unconfigured():
    """مكشطة غير مُهيَّأة = تعطيل نظيف: لا تغيير للتحليل، إبلاغ صريح، صفر كلود."""
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = _seed_research(db)
    with _env(SILK_API_KEY="secret", SILK_DB=db, SILK_GMAPS_SCRAPER_URL=None), \
         _no_claude():
        client = _client()
        r = client.post(f"/analyses/{aid}/enrich-leads",
                        headers={"X-API-Key": "secret"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enriched"] is False
    assert "غير مُهيَّأة" in body["note"]


def test_enrich_leads_404_for_missing_analysis():
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with _env(SILK_API_KEY="secret", SILK_DB=db,
              SILK_GMAPS_SCRAPER_URL="http://s:8080"), _no_claude():
        client = _client()
        r = client.post("/analyses/999999/enrich-leads",
                        headers={"X-API-Key": "secret"})
    assert r.status_code == 404


def test_enrich_leads_400_for_non_research_analysis():
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = _seed_analyze(db)
    with _env(SILK_API_KEY="secret", SILK_DB=db,
              SILK_GMAPS_SCRAPER_URL="http://s:8080"), _no_claude():
        client = _client()
        r = client.post(f"/analyses/{aid}/enrich-leads",
                        headers={"X-API-Key": "secret"})
    assert r.status_code == 400
    assert "deep_research" in r.text


def test_enrich_leads_stores_scraped_contacts_without_claude():
    """نجاح الكشط: هاتف/إيميل يُخزَّنان في التحليل المحفوظ، القالب الموحّد
    يُعاد بناؤه، وصفر نداء كلود (المسار الرخيص)."""
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = _seed_research(db)
    fake = {"leads": [{
        "name": "Gulf Dates BV", "address": "Rotterdam", "phone": "+31 10 123",
        "email": "sales@gulfdates.nl", "website": "gulfdates.nl",
        "rating": 4.5, "review_count": 30, "maps_link": "",
        "doc_level": "◐ مرصود عبر خرائط قوقل", "source": "google_maps_scraper"}],
        "path": "scraper", "note": "مرصود عبر مكشطة خرائط قوقل (هاتف/إيميل)"}
    with _env(SILK_API_KEY="secret", SILK_DB=db,
              SILK_GMAPS_SCRAPER_URL="http://s:8080",
              SILK_GMAPS_ENRICH_GRACE_S="2"), _no_claude(), \
         patch("silk_gmaps.submit_scrape_async", return_value=None), \
         patch("silk_gmaps.finalize_leads", return_value=fake):
        client = _client()
        r = client.post(f"/analyses/{aid}/enrich-leads",
                        headers={"X-API-Key": "secret"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enriched"] is True
        assert body["leads_count"] == 1
        assert body["path"] == "scraper"
        # ثابت في المخزن: نداء لاحق يقرأ الروابط الجديدة.
        import silk_storage as ST
        stored = ST.get_analysis(aid, path=db)
        leads = stored["deep_research"]["importer_leads"]["leads"]
        assert leads and leads[0]["phone"] == "+31 10 123"
        assert leads[0]["email"] == "sales@gulfdates.nl"


def test_enrich_leads_does_not_clobber_existing_on_gap():
    """فشل/فراغ الكشط لا يطمس روابط قائمة (لا اختلاق، لا فقدان)."""
    import silk_storage as ST
    from canonical_netherlands import netherlands_research_blob
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    blob = netherlands_research_blob()
    blob["deep_research"]["importer_leads"] = {
        "leads": [{"name": "Existing Co", "phone": "+44 1", "email": "",
                   "doc_level": "◐ مرصود عبر خرائط قوقل"}],
        "path": "scraper", "note": "سابق"}
    aid = ST.save_analysis(blob, path=db)
    gap = {"leads": [], "path": "gap", "note": "فجوة معلنة"}
    with _env(SILK_API_KEY="secret", SILK_DB=db,
              SILK_GMAPS_SCRAPER_URL="http://s:8080",
              SILK_GMAPS_ENRICH_GRACE_S="2"), _no_claude(), \
         patch("silk_gmaps.submit_scrape_async", return_value=None), \
         patch("silk_gmaps.finalize_leads", return_value=gap):
        client = _client()
        r = client.post(f"/analyses/{aid}/enrich-leads",
                        headers={"X-API-Key": "secret"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enriched"] is False
    assert body["leads_count"] == 1          # الروابط السابقة محفوظة
    stored = ST.get_analysis(aid, path=db)
    kept = stored["deep_research"]["importer_leads"]["leads"]
    assert kept and kept[0]["name"] == "Existing Co"


def test_enrich_leads_requires_api_key():
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    aid = _seed_research(db)
    with _env(SILK_API_KEY="secret", SILK_DB=db,
              SILK_GMAPS_SCRAPER_URL="http://s:8080"), _no_claude():
        client = _client()
        r = client.post(f"/analyses/{aid}/enrich-leads")   # بلا مفتاح
    assert r.status_code == 401

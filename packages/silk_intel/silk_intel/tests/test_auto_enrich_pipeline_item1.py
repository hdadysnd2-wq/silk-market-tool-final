"""أمر المالك المُحدَّث ITEM 1 — الإكمال التلقائي لبيانات المستوردين داخل
مسار `/research`: حين تكون المكشطة مُهيَّأة، تُجمَع جهات الاتصال (هاتف/إيميل/
موقع) **قبل الكاتب** فيشحن التقرير كاملاً من التشغيلة الأولى؛ وفشل/مهلة
المكشطة = فجوة معلنة والتشغيلة تكتمل (لا تعليق).

lock-tests (أمر المالك):
- pipeline-with-scraper-mock ⇒ روابط مُكمَّلة تظهر في docx العميل النهائي.
- scraper-down ⇒ فجوة معلنة والتشغيلة تكتمل بتقرير.

مموّه بالكامل (كلود عبر `_call_tools`/`_call`، المكشطة عبر `finalize_leads`) —
هرمتي، بلا شبكة.

Run: python3 -m pytest tests/test_auto_enrich_pipeline_item1.py -q
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("docx")


def _client():
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.app)


def _fake_call_tools(system, messages, tools=None, max_tokens=1600,
                     model=None, timeout=None):
    return {"stop_reason": "end_turn", "content": [
        {"type": "text", "text": json.dumps(
            {"findings": [], "gaps": [], "summary": "ok"})}]}


def _fake_call(system, user, max_tokens=1600, model=None, timeout=None):
    return json.dumps({"verdict": "WATCH", "confidence": 0.5, "reasoning": "ok"})


_ENRICHED = {
    "leads": [{
        "name": "Albion Dates Ltd", "address": "London", "phone": "+44 20 7946",
        "email": "buy@albiondates.co.uk", "website": "albiondates.co.uk",
        "rating": 4.6, "review_count": 42, "maps_link": "",
        "doc_level": "◐ مرصود عبر خرائط قوقل", "source": "google_maps_scraper"}],
    "path": "scraper", "note": "مرصود عبر مكشطة خرائط قوقل (هاتف/إيميل)"}


def _run(scraper_patch):
    """شغّل /research مموّهاً مع تصحيح مكشطة مُعطى؛ يعيد (data, db)."""
    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test",
                                 "SILK_API_KEY": "secret",
                                 "SILK_GMAPS_SCRAPER_URL": "http://s:8080",
                                 "SILK_HERMETIC": "1"}), \
         patch("silk_llm_runtime._call_tools", side_effect=_fake_call_tools), \
         patch("silk_synthesis._call", side_effect=_fake_call), \
         patch("silk_ai_judge._call", side_effect=_fake_call), \
         patch("silk_gmaps.submit_scrape_async", return_value=None), \
         scraper_patch, \
         patch("silk_storage._db_path", return_value=db):
        r = _client().post(
            "/research", headers={"X-API-Key": "secret"},
            json={"product": "عسل", "market": "United Kingdom",
                  "hs_code": "040900", "persist": True})
        assert r.status_code == 200, r.text
        data = r.json()
        # ابنِ docx العميل من السجل المخزَّن (داخل تصحيح _db_path).
        import silk_storage
        from silk_render import build_view
        from silk_reports import render_client_docx
        from conftest import docx_all_text
        found = silk_storage.get_analysis(data["analysis_id"])
        view = build_view(found)
        path = render_client_docx(view, os.path.join(tempfile.mkdtemp(), "c.docx"))
        docx_text = docx_all_text(path)
    return data, view, docx_text


def test_pipeline_with_scraper_mock_enriches_leads_in_final_docx():
    """مكشطة تُرجِع روابط ⇒ هاتف/إيميل يظهران في docx العميل النهائي،
    والمرحلة «enrich» جزء من مسار التشغيلة (قبل الكاتب)."""
    data, view, docx_text = _run(
        patch("silk_gmaps.finalize_leads", return_value=_ENRICHED))
    il = data["deep_research"]["importer_leads"]
    assert il["path"] == "scraper"
    assert il["leads"][0]["phone"] == "+44 20 7946"
    assert il["leads"][0]["email"] == "buy@albiondates.co.uk"
    # مرحلة الإكمال قائمة في المسار (بين التوليف والكاتب).
    assert "enrich" in (data["data_economics"].get("stage_seconds") or {})
    # التقرير النهائي (docx العميل) يحمل الهاتف/الإيميل فعلياً.
    assert "+44 20 7946" in docx_text
    assert "buy@albiondates.co.uk" in docx_text
    # التشغيلة اكتملت بتقرير (لا هيكل).
    assert data["deep_research"]["report"]["report"]


def test_pipeline_scraper_down_declares_gap_and_run_completes():
    """فشل المكشطة ⇒ فجوة معلنة (path=gap، بلا روابط) والتشغيلة تكتمل
    بتقرير — لا تعليق، لا اختلاق صفّ."""
    def _boom(*a, **k):
        raise OSError("scraper unreachable (net blocked for offline test)")
    data, view, docx_text = _run(
        patch("silk_gmaps.finalize_leads", side_effect=_boom))
    il = data["deep_research"]["importer_leads"]
    assert il["path"] == "gap"
    assert (il.get("leads") or []) == []
    # التشغيلة اكتملت رغم سقوط المكشطة.
    assert data["deep_research"]["report"]["report"]
    assert "enrich" in (data["data_economics"].get("stage_seconds") or {})
    # docx العميل يعلن الفجوة بلغة تجارية (لا صفّ مخترَع).
    assert "لم تُرصَد جهات اتصال" in docx_text

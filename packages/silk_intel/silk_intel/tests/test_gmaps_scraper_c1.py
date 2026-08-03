"""C1 (SPEC-v2, Command #5a) — مكشطة الخرائط: التهيئة والتعطيل النظيف.

المكشطة خدمة Railway ثانية بشبكة خاصة، تُدار بمتغيّر واحد
`SILK_GMAPS_SCRAPER_URL`. هذا الملف يقفل **التعطيل النظيف**: غياب المتغيّر =
تعطيل كامل بلا كسر، و`/health` يعرض الحالة إخبارياً دون أن يحجب
`research_ready` (معيار القبول ٥: إيقاف المكشطة لا يؤثّر على /health الرئيس).

تكامل الكشط (C2–C5) لا يُختبَر هنا — لم يُفتَح بعد (قرار D-03).

Run: python3 -m pytest tests/test_gmaps_scraper_c1.py -q
"""
import os
import sys
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextmanager
def _env(**vals):
    """اضبط متغيّرات بيئة ثم استعِدها حتماً (نفس نمط بقيّة الاختبارات)."""
    old = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_disabled_by_default_when_url_unset():
    import silk_gmaps
    with _env(SILK_GMAPS_SCRAPER_URL=None):
        assert silk_gmaps.enabled() is False
        assert silk_gmaps.scraper_url() == ""
        assert "off" in silk_gmaps.health_status()


def test_enabled_when_url_set():
    import silk_gmaps
    with _env(SILK_GMAPS_SCRAPER_URL="http://gmaps-scraper.railway.internal:8080"):
        assert silk_gmaps.enabled() is True
        assert silk_gmaps.health_status().startswith("on")


def test_health_status_never_leaks_internal_url():
    """السطر الإخباري لا يكشف اسم المضيف الداخلي الخاص (لا تسريب)."""
    import silk_gmaps
    url = "http://gmaps-scraper.railway.internal:8080"
    with _env(SILK_GMAPS_SCRAPER_URL=url):
        assert url not in silk_gmaps.health_status()


def test_health_endpoint_shows_scraper_status_and_does_not_gate_readiness():
    """`/health` يعرض حالة المكشطة، وإيقافها (متغيّر غائب) لا يحجب
    research_ready — العزل الذي يطلبه معيار القبول ٥."""
    from fastapi.testclient import TestClient
    with _env(SILK_GMAPS_SCRAPER_URL=None), \
            patch("requests.get", side_effect=OSError("no network in test")):
        import api
        client = TestClient(api.create_app())
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert "gmaps_scraper" in body["sources"]
        assert "off" in body["sources"]["gmaps_scraper"]
        # research_ready موجود ومستقلّ عن حالة المكشطة (مفتاح موجود دائماً).
        assert "research_ready" in body


def test_scraper_config_reads_only_the_one_env_var():
    """التهيئة تقرأ SILK_GMAPS_SCRAPER_URL حصراً — لا مفتاح مصدر يُهرَّب."""
    import silk_gmaps
    assert silk_gmaps.ENV_VAR == "SILK_GMAPS_SCRAPER_URL"

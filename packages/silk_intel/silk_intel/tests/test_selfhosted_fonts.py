"""اختبار البند 12 — خطوط مستضافة ذاتياً، لا CDN خارجي (TASK_BRIEF §12).

يقفل: (١) الواجهة لا تشير لأي مضيف خطوط خارجي؛ (٢) حزمة الخطوط المحلية
موجودة فعلاً (fonts.css + ملفات woff2 للعربية واللاتينية)؛ (٣) سياسة CSP
لا تسمح بمضيف خطوط خارجي بعد الآن.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_index_has_no_external_font_hosts():
    html = open(os.path.join(_ROOT, "web", "index.html"), encoding="utf-8").read()
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert 'href="fonts/fonts.css"' in html


def test_local_font_bundle_present():
    d = os.path.join(_ROOT, "web", "fonts")
    css = open(os.path.join(d, "fonts.css"), encoding="utf-8").read()
    files = os.listdir(d)
    woff2 = [f for f in files if f.endswith(".woff2")]
    assert woff2, "لا ملفات خطوط محلية"
    # العائلات الثلاث حاضرة، والعربية مشمولة فعلاً.
    for fam in ("IBM Plex Sans Arabic", "Markazi Text", "IBM Plex Mono"):
        assert fam in css
    assert any("-arabic.woff2" in f for f in woff2)
    # كل ملف مُشار إليه في CSS موجود فعلاً — لا رابط مكسور.
    import re
    for ref in re.findall(r"url\('([^']+)'\)", css):
        assert ref in files, f"font file missing: {ref}"


def test_csp_has_no_external_font_hosts():
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.create_app())
    csp = client.get("/health").headers.get("Content-Security-Policy") or ""
    assert "fonts.googleapis.com" not in csp
    assert "fonts.gstatic.com" not in csp
    assert "font-src 'self'" in csp

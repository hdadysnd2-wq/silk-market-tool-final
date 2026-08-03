"""WS8 — سلسلة الأخبار المتدرّجة GDELT → Google News RSS → Serper.

يثبت العقود بلا شبكة (هرمتي):
  • موصّل Google News RSS: نجاح يفكّ XML لعناوين حقيقية؛ شبكة مقطوعة/جسم
    غير-XML/استعلام فارغ/لا عناصر => `DataPoint` موسوم `None` لا اختلاق.
  • سلسلة `news_with_fallback`: تُرجِع أوّل تِيرٍ يحمل عنواناً؛ استنفاد
    السلسلة كاملةً => فجوة معلنة واحدة تسمّي الروابط المُجرَّبة، لا اختلاق.

Run:  python3 -m pytest tests/test_ws8_news_fallback_chain.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network  # noqa: E402

from silk_data_layer import DataPoint, _today  # noqa: E402

_RSS_OK = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Google News</title>
  <item>
    <title>Peanut butter demand rises in the Netherlands</title>
    <link>https://example-news.nl/story/1</link>
    <pubDate>Mon, 21 Jul 2026 08:00:00 GMT</pubDate>
    <source url="https://example-news.nl">Example News NL</source>
  </item>
  <item>
    <title>Retail spread prices tracked across EU markets</title>
    <link>https://www.eu-retail.example/story/2</link>
    <pubDate>Tue, 22 Jul 2026 09:00:00 GMT</pubDate>
    <source url="https://eu-retail.example">EU Retail</source>
  </item>
</channel></rss>"""


class _FakeResp:
    def __init__(self, content=b"", status=200, ctype="application/xml"):
        self.content = content
        self.status_code = status
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# ----------------------------- الموصّل -----------------------------

def test_rss_success_parses_real_headlines(monkeypatch):
    import silk_google_news_agent as gn

    monkeypatch.setattr(gn.requests, "get", lambda *a, **k: _FakeResp(_RSS_OK))
    out = gn.google_news_rss("peanut butter", "Netherlands", gl="NL", hl="en")
    titles = [dp.value["title"] for dp in out if dp.value]
    assert len(titles) == 2
    assert "Peanut butter demand rises in the Netherlands" in titles
    # النطاق مشتقّ من الرابط بلا اختلاق، والـ source_id عمومي (WS9).
    assert out[0].value["domain"] == "example-news.nl"
    assert out[0].value["source_id"] == gn.SOURCE_ID
    assert 0.0 < out[0].confidence <= 1.0


def test_empty_query_returns_tagged_none_no_network():
    import silk_google_news_agent as gn

    with block_network():
        out = gn.google_news_rss("", "Netherlands")
    assert len(out) == 1 and out[0].value is None and out[0].confidence == 0.0


def test_network_cut_degrades_to_tagged_none():
    import silk_google_news_agent as gn

    with block_network():
        out = gn.google_news_rss("dates exports", "Nigeria")
    assert out[0].value is None and out[0].source == gn.SOURCE_ID
    assert "failed" in out[0].note.lower() or "google news" in out[0].note.lower()


def test_non_xml_body_is_distinct_declared_gap(monkeypatch):
    import silk_google_news_agent as gn

    # جسم HTML غير سليم XML (رمز & عارٍ) — نمط صفحة حجب WAF شائع.
    monkeypatch.setattr(gn.requests, "get",
                        lambda *a, **k: _FakeResp(b"<html>blocked & down</html>",
                                                  ctype="text/html"))
    out = gn.google_news_rss("x", "y")
    assert out[0].value is None
    assert "non-XML" in out[0].note


def test_no_items_returns_declared_gap(monkeypatch):
    import silk_google_news_agent as gn

    empty = b"<?xml version='1.0'?><rss><channel></channel></rss>"
    monkeypatch.setattr(gn.requests, "get", lambda *a, **k: _FakeResp(empty))
    out = gn.google_news_rss("obscure query", "Nowhere")
    assert out[0].value is None and out[0].confidence == 0.0


# ----------------------------- السلسلة -----------------------------

def _gap(src):
    return [DataPoint(None, src, 0.0, "declared gap", _today())]


def _headline(src):
    return [DataPoint({"title": f"{src} headline", "url": "", "date": "",
                       "domain": "", "source_id": src}, src, 0.6, "n", _today())]


def test_chain_returns_gdelt_when_gdelt_has_headlines(monkeypatch):
    import silk_google_news_agent as gn

    monkeypatch.setattr("silk_gdelt_agent.gdelt_news",
                        lambda *a, **k: _headline("GDELT"))
    # لا ينبغي بلوغ التِير الأوسط إطلاقاً — نُفشِله لو استُدعي.
    monkeypatch.setattr(gn, "google_news_rss",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    out = gn.news_with_fallback("q", "Netherlands")
    assert out[0].value["source_id"] == "GDELT"


def test_chain_falls_to_google_news_when_gdelt_empty(monkeypatch):
    import silk_google_news_agent as gn

    monkeypatch.setattr("silk_gdelt_agent.gdelt_news", lambda *a, **k: _gap("GDELT"))
    monkeypatch.setattr(gn, "google_news_rss", lambda *a, **k: _headline(gn.SOURCE_ID))
    out = gn.news_with_fallback("q", "Netherlands")
    assert out[0].value and out[0].source == gn.SOURCE_ID


def test_chain_falls_to_serper_when_gdelt_and_gnews_empty(monkeypatch):
    import silk_google_news_agent as gn

    monkeypatch.setattr("silk_gdelt_agent.gdelt_news", lambda *a, **k: _gap("GDELT"))
    monkeypatch.setattr(gn, "google_news_rss", lambda *a, **k: _gap(gn.SOURCE_ID))
    monkeypatch.setattr("silk_websearch_agent.web_search",
                        lambda *a, **k: _headline("Web Search"))
    out = gn.news_with_fallback("q", "Netherlands")
    assert out[0].value and out[0].source == "Web Search"


def test_chain_exhausted_declares_single_gap_naming_links(monkeypatch):
    import silk_google_news_agent as gn

    monkeypatch.setattr("silk_gdelt_agent.gdelt_news", lambda *a, **k: _gap("GDELT"))
    monkeypatch.setattr(gn, "google_news_rss", lambda *a, **k: _gap(gn.SOURCE_ID))
    monkeypatch.setattr("silk_websearch_agent.web_search",
                        lambda *a, **k: _gap("Web Search"))
    out = gn.news_with_fallback("q", "Netherlands")
    assert len(out) == 1 and out[0].value is None and out[0].confidence == 0.0
    # الفجوة تسمّي الروابط المُستنفَدة الثلاثة — قابلية تدقيق (لا اختلاق).
    assert "GDELT" in out[0].note
    assert gn.SOURCE_ID in out[0].note
    assert "Web Search" in out[0].note


def test_google_news_resolves_to_official_public_url_ws9():
    # WS9: مصدرٌ مسمّى يحلّ لرابطه الرسمي في المراجع، لا نائبٍ عام.
    from silk_data_layer import public_source_url
    import silk_google_news_agent as gn

    assert public_source_url(gn.SOURCE_ID) == "https://news.google.com/"
    # يصيب حتى مع لاحقة عربية بين قوسين (مطابقة الاسم القاعدي).
    assert public_source_url(f"{gn.SOURCE_ID} (آخر ١٢ شهراً)") == \
        "https://news.google.com/"


def test_chain_survives_a_raising_link(monkeypatch):
    import silk_google_news_agent as gn

    def _boom(*a, **k):
        raise RuntimeError("gdelt exploded")

    monkeypatch.setattr("silk_gdelt_agent.gdelt_news", _boom)
    monkeypatch.setattr(gn, "google_news_rss", lambda *a, **k: _headline(gn.SOURCE_ID))
    # استثناء تِيرٍ لا يكسر السلسلة — يسقط للتِير التالي (تعطيل نظيف).
    out = gn.news_with_fallback("q", "Netherlands")
    assert out[0].value and out[0].source == gn.SOURCE_ID

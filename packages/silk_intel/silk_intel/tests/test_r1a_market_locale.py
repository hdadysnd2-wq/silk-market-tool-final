"""اختبارات PR-A (R1 البنية التحتية): مرجع لغة/عملة/متاجر السوق + تمرير
gl/hl لبحث الويب — كي يبحث النظام كمستهلك محلي بدل التخمين.

المبدأ المؤسِّس محفوظ: بلا مفتاح/شبكة => value None وconfidence 0.0 (لا اختلاق).
gl/hl مشتقّان من السوق (لا مُخمَّنان)؛ غيابهما => بحث عام كالسابق (لا كسر توافق).
Run:  python3 -m pytest tests/test_r1a_market_locale.py -q
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resp(payload):
    m = mock.MagicMock(status_code=200)
    m.raise_for_status.return_value = None
    m.json.return_value = payload
    return m


def _market(name="Nigeria"):
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market(name)
    return ref


# ── جدول market_locale.csv ────────────────────────────────────────────────

def test_locale_table_covers_every_ranked_market():
    """تغطية كاملة لأسواق سِلك الـ38 (silk_market_ranker.COUNTRIES) — سوق
    مرتَّب بلا صف locale = فجوة صامتة في توجيه البحث."""
    import silk_market_ranker as R
    import silk_llm_runtime as RT
    rows = RT._load_csv(RT._REF_TABLES["locale"])
    have = {(r.get("iso3") or "").strip().upper() for r in rows}
    want = {c["iso3"] for c in R.COUNTRIES}
    missing = want - have
    assert not missing, f"أسواق بلا صف locale: {sorted(missing)}"


def test_locale_rows_have_valid_gl_hl_currency():
    """كل صف يحمل نطاق دولة (حرفان) ولغة أساسية وعملة (٣ أحرف) — البيانات
    المعيارية (ISO) شبه مؤكدة؛ صفّ ناقص يُفسد الاستهداف بصمت."""
    import silk_llm_runtime as RT
    for r in RT._load_csv(RT._REF_TABLES["locale"]):
        iso3 = r.get("iso3")
        assert len((r.get("gl") or "").strip()) == 2, f"gl خاطئ لِ {iso3}"
        assert (r.get("lang_primary") or "").strip(), f"لا لغة أساسية لِ {iso3}"
        assert len((r.get("currency") or "").strip()) == 3, f"عملة خاطئة لِ {iso3}"


# ── lookup_reference table='locale' ───────────────────────────────────────

def test_lookup_reference_locale_returns_market_row():
    import silk_llm_runtime as RT
    ctx = {"market": _market("China"), "hs_code": "080410"}
    out = RT._tool_lookup_reference({"table": "locale"}, ctx)
    assert out and out[0].value is not None
    row = out[0].value
    assert row["gl"] == "cn"
    assert row["lang_primary"] == "zh-CN"
    assert "Tmall" in (row.get("marketplaces") or "")


def test_lookup_reference_locale_declares_gap_for_market_without_row():
    """سوق خارج التغطية => فجوة معلنة (value None, conf 0.0) لا اختلاق."""
    import silk_llm_runtime as RT
    from silk_market_resolver import MarketRef
    fake = MarketRef(iso3="ZWE", m49="716", name_en="Zimbabwe", name_ar="زيمبابوي")
    out = RT._tool_lookup_reference({"table": "locale"}, {"market": fake})
    assert out[0].value is None
    assert out[0].confidence == 0.0
    assert "ZWE" in out[0].note


# ── مشتقّات locale ─────────────────────────────────────────────────────────

def test_locale_helpers_derive_gl_and_hl_from_table():
    import silk_llm_runtime as RT
    ctx = {"market": _market("Germany")}
    assert RT._locale_gl(ctx) == "de"
    assert RT._locale_hl(ctx) == "de"
    # سوق غير لاتيني — hl صيني، gl صيني
    ctx_cn = {"market": _market("China")}
    assert RT._locale_gl(ctx_cn) == "cn"
    assert RT._locale_hl(ctx_cn) == "zh-cn"


def test_locale_helpers_empty_for_unknown_market():
    import silk_llm_runtime as RT
    from silk_market_resolver import MarketRef
    fake = MarketRef(iso3="ZWE", m49="716", name_en="Zimbabwe", name_ar="ز")
    assert RT._locale_gl({"market": fake}) == ""
    assert RT._locale_hl({"market": fake}) == ""


# ── web_search(gl, hl) — نداء Serper الفعلي ───────────────────────────────

def test_web_search_passes_gl_hl_to_serper_body():
    import silk_websearch_agent as W
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return _resp({"organic": [
            {"title": "价格", "snippet": "s", "link": "https://x.cn/y"}]})

    with mock.patch.dict(os.environ, {"SEARCH_API_KEY": "k"}), \
         mock.patch("requests.post", fake_post):
        out = W.web_search("果汁 价格", num=3, gl="cn", hl="zh-cn")
    assert calls[0]["gl"] == "cn"
    assert calls[0]["hl"] == "zh-cn"
    assert out[0].value["title"] == "价格"


def test_web_search_omits_gl_hl_when_absent_backward_compatible():
    """غياب gl/hl => جسم النداء بلا هذين المفتاحين (نفس السلوك القديم)."""
    import silk_websearch_agent as W
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return _resp({"organic": [{"title": "t", "snippet": "s", "link": "l"}]})

    with mock.patch.dict(os.environ, {"SEARCH_API_KEY": "k"}), \
         mock.patch("requests.post", fake_post):
        W.web_search("juice price", num=2)
    assert "gl" not in calls[0] and "hl" not in calls[0]


def test_web_search_offline_no_key_declares_gap_not_fabricate():
    """بلا مفتاح => value None, conf 0.0 (المبدأ المؤسِّس) حتى مع gl/hl."""
    import silk_websearch_agent as W
    with mock.patch.dict(os.environ, {}, clear=True):
        out = W.web_search("price", gl="cn", hl="zh-cn")
    assert out[0].value is None
    assert out[0].confidence == 0.0


# ── _tool_web_search: اشتقاق gl/hl تلقائياً من السوق ──────────────────────

def test_tool_web_search_auto_applies_market_locale():
    """كلود لا يمرّر gl/hl؛ الأداة تشتقّهما من مرجع السوق تلقائياً — هذا هو
    جوهر 'البحث بلغة السوق' آلياً لا اجتهاداً."""
    import silk_llm_runtime as RT
    captured = {}

    def fake_web_search(query, num=5, gl=None, hl=None):
        captured.update(query=query, gl=gl, hl=hl)
        from silk_data_layer import DataPoint, _today
        return [DataPoint({"title": "t", "snippet": "s", "link": "l"},
                          "Web Search (Serper)", 0.5, "ok", _today())]

    ctx = {"market": _market("China"), "hs_code": "080410"}
    with mock.patch("silk_websearch_agent.web_search", fake_web_search):
        RT._tool_web_search({"query": "果汁"}, ctx)
    assert captured["gl"] == "cn"
    assert captured["hl"] == "zh-cn"


def test_tool_web_search_explicit_args_override_market_locale():
    """وسيط كلود الصريح يتجاوز الاشتقاق التلقائي (لتجاوز مقصود)."""
    import silk_llm_runtime as RT
    captured = {}

    def fake_web_search(query, num=5, gl=None, hl=None):
        captured.update(gl=gl, hl=hl)
        from silk_data_layer import DataPoint, _today
        return [DataPoint({"title": "t"}, "Web Search (Serper)", 0.5, "ok", _today())]

    ctx = {"market": _market("China")}
    with mock.patch("silk_websearch_agent.web_search", fake_web_search):
        RT._tool_web_search({"query": "x", "gl": "us", "hl": "en"}, ctx)
    assert captured["gl"] == "us" and captured["hl"] == "en"

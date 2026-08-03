"""اختبارات الموجة ٨ — أداء (P1) + ترويسات أمان (L-2).

يقفل:
1. Q4: الدخل يُجلب **مرّة واحدة** لكل سوق (كان مرّتين) — اختبار انحدار.
2. التوازي (ThreadPoolExecutor) يحفظ كل الأسواق وترتيبها كالتسلسلي (لا سباق).
3. الجلسة المجمّعة موجودة ومربوطة بمُحوِّل تجميع (keep-alive).
4. L-2: ترويسات الأمان (CSP + nosniff + Referrer-Policy) على كل ردّ.
Run:  python3 -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_data_layer import DataPoint


def test_q4_income_fetched_once_per_market(monkeypatch):
    # Q4: الدخل يُجلب مرّة واحدة ويُعاد استعماله للمكوّن ولحقل اللوحة (كان مرّتين).
    import silk_market_ranker as R
    calls = {"ppp": 0, "gdp": 0}

    def ppp(iso3, year=None):
        calls["ppp"] += 1
        return DataPoint(50000.0, "World Bank", 0.95, "ppp")

    def gdp(iso3, year=None):
        calls["gdp"] += 1
        return DataPoint(None, "World Bank", 0.0, "no gdp")

    monkeypatch.setattr(R, "ppp_per_capita", ppp)
    monkeypatch.setattr(R, "gdp_per_capita", gdp)
    monkeypatch.setattr(R, "market_imports",
                        lambda hs, m, y: {"total_usd": 1.0, "competitors": []})
    monkeypatch.setattr(R, "population",
                        lambda iso3, year=None: DataPoint(1000.0, "World Bank", 0.9, "pop"))

    out = R.rank_markets("080410", countries=[{"iso3": "ARE", "m49": "784"}],
                         year=2023)
    assert len(out) == 1
    assert calls["ppp"] == 1          # مرّة واحدة — كان 2 قبل الإصلاح
    assert calls["gdp"] == 0          # ppp نجح => لا احتياط
    assert out[0]["income_ppp"] == 50000.0       # الحقل يعيد استعمال نفس الجلب
    assert out[0]["components"]["demand_capacity"].value == 50000.0


def test_concurrent_gather_preserves_markets_and_order(monkeypatch):
    # التوازي لا يُسقط سوقاً ولا يكرّره ولا يغيّر الترتيب (لا سباق) — مطابق للتسلسلي.
    import silk_market_ranker as R
    sizes = {"784": 300.0, "826": 100.0, "276": 200.0}   # حجم مميّز لكل سوق
    monkeypatch.setattr(R, "market_imports",
                        lambda hs, m, y: {"total_usd": sizes[str(m)], "competitors": []})
    monkeypatch.setattr(R, "ppp_per_capita",
                        lambda iso3, year=None: DataPoint(1.0, "WB", 0.9, "x"))
    monkeypatch.setattr(R, "gdp_per_capita",
                        lambda iso3, year=None: DataPoint(1.0, "WB", 0.9, "x"))
    monkeypatch.setattr(R, "population",
                        lambda iso3, year=None: DataPoint(1.0, "WB", 0.9, "p"))
    cs = [{"iso3": "ARE", "m49": "784"}, {"iso3": "GBR", "m49": "826"},
          {"iso3": "DEU", "m49": "276"}]
    out = R.rank_markets("x", countries=cs, year=2023, max_workers=8)
    assert len(out) == 3                                    # لا فقد/تكرار
    assert {r["iso3"] for r in out} == {"ARE", "GBR", "DEU"}
    assert [r["iso3"] for r in out] == ["ARE", "DEU", "GBR"]  # حجم أعلى => أعلى
    out2 = R.rank_markets("x", countries=cs, year=2023, max_workers=8)
    assert [r["iso3"] for r in out2] == [r["iso3"] for r in out]  # ثابت (لا سباق)


def test_pooled_session_is_configured():
    # الجلسة المجمّعة موجودة بمُحوِّل تجميع (keep-alive) — لا httpx، لا تبعية جديدة.
    import silk_data_layer as D
    import requests
    assert isinstance(D._session, requests.Session)
    adapter = D._session.get_adapter("https://comtradeapi.un.org")
    assert isinstance(adapter, requests.adapters.HTTPAdapter)


def test_l2_security_headers_present():
    # L-2: كل ردّ يحمل CSP + nosniff + Referrer-Policy.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import api
    client = TestClient(api.create_app())
    r = client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    csp = r.headers.get("Content-Security-Policy") or ""
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp

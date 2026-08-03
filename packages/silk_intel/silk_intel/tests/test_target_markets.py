"""اختبارات منتقي الأسواق المستهدفة — target-market picker (رد على «ليش ما
اقدر احدد دولة»؛ المنصة كانت ترتّب كل الأسواق الـ٣٨ دون قدرة على تضييقها).

يقفل: `GET /markets` مرجع الأسواق (بلا مفتاح، أسماء حقيقية لا مُخترعة)؛
حقل `markets` في `/analyze` يضيّق المرشّحين فعلياً عبر `silk_engine.analyze`؛
رموز مجهولة تُتجاهَل بصمت لا تُسقِط التحليل؛ الغياب/الفراغ = السلوك القديم
(كل الأسواق) بلا تغيير — لا انحدار.
"""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _client():
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import importlib
    import api
    os.environ.pop("SILK_API_KEY", None)
    os.environ["SILK_RATE_LIMIT"] = "0"
    importlib.reload(api)
    return TestClient(api.create_app()), api


def test_markets_reference_returns_named_candidates_no_key_required():
    client, _ = _client()
    r = client.get("/markets")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 38
    assert all({"iso3", "m49", "name"} <= set(row) for row in rows)
    chn = next(row for row in rows if row["iso3"] == "CHN")
    assert chn["name"] == "China"          # اسم حقيقي من PARTNER_NAMES، لا مُخترع


def test_analyze_with_markets_field_narrows_the_candidate_set():
    client, api_mod = _client()
    captured = {}

    def spy(product, **kw):
        captured.update(kw)
        return {"product": product, "classified": False, "markets": [],
                "hs_code": None, "hs_note": "x", "note": "x"}

    with mock.patch("silk_engine.analyze", spy):
        r = client.post("/analyze", json={"product": "تمور",
                                          "markets": ["CHN", "DEU"]})
    assert r.status_code == 200
    countries = captured.get("countries")
    assert countries is not None
    assert {c["iso3"] for c in countries} == {"CHN", "DEU"}


def test_analyze_without_markets_field_keeps_full_discovery_behavior():
    client, api_mod = _client()
    captured = {}

    def spy(product, **kw):
        captured.update(kw)
        return {"product": product, "classified": False, "markets": [],
                "hs_code": None, "hs_note": "x", "note": "x"}

    with mock.patch("silk_engine.analyze", spy):
        client.post("/analyze", json={"product": "تمور"})
    assert captured.get("countries") is None   # الافتراضي القديم — لا انحدار


def test_analyze_with_unknown_market_codes_ignored_not_fabricated():
    client, api_mod = _client()
    captured = {}

    def spy(product, **kw):
        captured.update(kw)
        return {"product": product, "classified": False, "markets": [],
                "hs_code": None, "hs_note": "x", "note": "x"}

    with mock.patch("silk_engine.analyze", spy):
        client.post("/analyze", json={"product": "تمور",
                                      "markets": ["ZZZ", "CHN"]})
    countries = captured.get("countries")
    assert countries is not None
    assert {c["iso3"] for c in countries} == {"CHN"}     # ZZZ يُتجاهَل بصمت


def test_analyze_with_only_unknown_codes_falls_back_to_full_discovery():
    """كل الرموز مجهولة => لا يسقط التحليل لصفر أسواق — يعود للاكتشاف الكامل."""
    client, api_mod = _client()
    captured = {}

    def spy(product, **kw):
        captured.update(kw)
        return {"product": product, "classified": False, "markets": [],
                "hs_code": None, "hs_note": "x", "note": "x"}

    with mock.patch("silk_engine.analyze", spy):
        client.post("/analyze", json={"product": "تمور", "markets": ["ZZZ"]})
    assert captured.get("countries") is None


def test_ui_has_target_market_picker_wired_to_analyze_body():
    html = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web", "index.html"),
        encoding="utf-8").read()
    assert '"/markets"' in html
    # الواجهة الجديدة: اختيار سوق واحد أو «كل الأسواق» — التقييد يمرّ
    # markets:[iso3] في جسم /analyze، نفس عقد الخادم.
    assert "b.markets=[S.market.iso3]" in html
    assert "b.markets=" in html

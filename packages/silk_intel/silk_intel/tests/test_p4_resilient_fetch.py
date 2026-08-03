"""اختبارات 1b — الجلب المرن: إعادة محاولة، مباعدة، وتمييز تعذّر الجلب.

بلاغ المالك الحرج: تحليل سنغافورة 2024 عاد «لا واردات مرصودة» بينما كومتريد
يملك 17.4M$ فعلاً — المنصة ضربت حدّ المعدل (429) وسجّلت فشل الجلب على أنه
«لا بيانات». يقفل هذا الملف: (١) إعادة المحاولة بتراجع أسّي على 429/5xx مع
احترام Retry-After؛ (٢) مباعدة النداءات لكل مضيف؛ (٣) العقد الجديد
comtrade_trade: None=تعذّر الجلب، []=ردّ ناجح بلا سجل؛ (٤) status على
DataPoint يصل القالب فيعرض «أعد المحاولة» لا «—» الموهمة.
Run:  python3 -m pytest tests/test_p4_resilient_fetch.py -q
"""
import os
import sys
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

import silk_data_layer as DL  # noqa: E402


class _Resp:
    def __init__(self, code, payload=None, headers=None):
        self.status_code = code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_http_get_retries_429_then_succeeds_and_honors_retry_after():
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return _Resp(429, headers={"Retry-After": "0"})
        return _Resp(200, {"data": [1]})

    slept = []
    with mock.patch.object(DL._session, "get", side_effect=fake_get), \
         mock.patch.object(DL._time, "sleep", side_effect=slept.append):
        r = DL._http_get("https://comtradeapi.un.org/x")
    assert r.status_code == 200 and calls["n"] == 3
    # احترم Retry-After: 0 كأساس (لا تراجع أسّي 1.0/2.0) — منذ بلاغ 429
    # (الموجة p4) يُضاف تشويش صغير ≤0.5ث فوق الأساس لفكّ تزامن النداءات
    # المتوازية، فالمساواة الحرفية بالصفر لم تعد الشكل الصحيح للقصد نفسه.
    assert len(slept) == 2
    assert all(0.0 <= s <= 0.5 for s in slept), slept


def test_http_get_gives_up_after_retries_returns_last_response():
    def always_429(url, params=None, timeout=None):
        return _Resp(429)
    with mock.patch.object(DL._session, "get", side_effect=always_429), \
         mock.patch.object(DL._time, "sleep"):
        r = DL._http_get("https://comtradeapi.un.org/x")
    assert r.status_code == 429       # يعاد الردّ الأخير — المستهلك يقرّر


def test_throttle_spaces_calls_per_host():
    DL._last_hit.clear()
    with mock.patch.dict(os.environ, {"SILK_HTTP_MIN_GAP_MS": "40"}):
        t0 = time.monotonic()
        DL._throttle("h1"); DL._throttle("h1"); DL._throttle("h1")
        elapsed = time.monotonic() - t0
    assert elapsed >= 0.06            # نداءان إضافيان × 40ms مباعدة تقريباً
    with mock.patch.dict(os.environ, {"SILK_HTTP_MIN_GAP_MS": "0"}):
        t0 = time.monotonic()
        for _ in range(5):
            DL._throttle("h2")
        assert time.monotonic() - t0 < 0.02   # الصفر يعطّلها (الاختبارات)


def test_comtrade_trade_none_on_failure_empty_list_on_no_record():
    with block_network():             # فشل شبكي حقيقي => None
        assert DL.comtrade_trade("040900", "702", 2024) is None
    with mock.patch.object(DL, "_cached_get",
                           return_value={"data": []}):    # ردّ ناجح فارغ => []
        assert DL.comtrade_trade("040900", "702", 2024) == []


def test_tradeflow_agent_distinguishes_fetch_failed_from_no_record():
    import silk_agents as A
    with mock.patch.object(A, "comtrade_trade", return_value=None):
        rep = A.TradeFlowAgent().run({"hs_code": "040900",
                                      "market_m49": "702", "year": 2024})
    assert all(f.value is None for f in rep.findings)      # الثابت: لا رقم
    assert all(f.status == "fetch_failed" for f in rep.findings)
    assert any("أعد المحاولة" in f.note for f in rep.findings)

    with mock.patch.object(A, "comtrade_trade", return_value=[]):
        rep2 = A.TradeFlowAgent().run({"hs_code": "040900",
                                       "market_m49": "702", "year": 2024})
    assert all(f.value is None for f in rep2.findings)
    assert all(f.status == "no_record" for f in rep2.findings)
    assert not any("أعد المحاولة" in f.note for f in rep2.findings)


def test_fetch_failed_flows_to_view_component_status():
    import silk_market_ranker as R
    from silk_render import build_view
    dp = R._market_size_component(None, "040900", "702", 2024,
                                  fetch_failed=True)
    assert dp.status == "fetch_failed" and dp.value is None
    assert "أعد المحاولة" in dp.note
    view = build_view({"product": "عسل", "hs_code": "040900", "year": 2024,
                       "classified": True,
                       "markets": [{"country": "Singapore", "iso3": "SGP",
                                    "m49": "702", "total_score": 0.0,
                                    "confidence": 0.0,
                                    "components": {"market_size": dp}}]})
    c = view["markets"][0]["components_detail"][0]
    assert c["status"] == "fetch_failed"       # القالب يميّز — لا «—» موهمة


def test_market_imports_flags_fetch_failure():
    import silk_data_layer_v2 as V2
    with mock.patch.object(V2, "comtrade_trade", return_value=None):
        mi = V2.market_imports("040900", "702", 2024)
    assert mi["total_usd"] is None and mi.get("fetch_failed") is True
    with mock.patch.object(V2, "comtrade_trade", return_value=[]):
        mi2 = V2.market_imports("040900", "702", 2024)
    assert mi2["total_usd"] is None and not mi2.get("fetch_failed")

"""اختبارات أسعار Google Shopping المجانية عبر Serper — رد على طلب مالك مباشر:
"اي سعر في اي منصة حسب كل دولة" (بديل مجاني عن `retail_prices` المهيكلة
المدفوعة، حين لا تُتاح طبقة /deepen). لا استخراج نصي حر من عنوان صفحة —
السعر يأتي من حقل `price` المنظَّم في نتيجة التسوق نفسها؛ سلسلة بلا رقم
واضح تُسقَط لا تُخمَّن، والقيمة الخام تبقى محفوظة دوماً.
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


# ── _parse_price: الدالة النقية ───────────────────────────────────────────────

def test_parse_price_extracts_amount_and_known_currency_symbol():
    import silk_websearch_agent as W
    assert W._parse_price("$4.99") == (4.99, "USD")
    assert W._parse_price("AED 10.00") == (10.0, "AED")
    assert W._parse_price("1,250 SAR") == (1250.0, "SAR")
    assert W._parse_price("﷼15.50") == (15.5, "SAR")


def test_parse_price_no_digits_is_declared_none_not_guessed():
    import silk_websearch_agent as W
    assert W._parse_price("") == (None, None)
    assert W._parse_price("Contact for price") == (None, None)
    assert W._parse_price(None) == (None, None)


def test_parse_price_unknown_currency_keeps_amount_currency_none():
    import silk_websearch_agent as W
    amount, currency = W._parse_price("42.5 XYZ")
    assert amount == 42.5 and currency is None   # لا تخمين عملة غير معروفة


# ── web_search_shopping: نداء Serper الفعلي بالدولة ──────────────────────────

def test_web_search_shopping_passes_gl_and_parses_structured_prices():
    import silk_websearch_agent as W
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return _resp({"shopping": [
            {"title": "Fresh Juice 1L", "price": "AED 12.00",
             "source": "Carrefour UAE", "link": "https://carrefouruae.com/x"},
            {"title": "No price listing", "price": "", "source": "X",
             "link": "https://x.example/y"}]})

    with mock.patch.dict(os.environ, {"SEARCH_API_KEY": "k"}), \
         mock.patch("requests.post", fake_post):
        out = W.web_search_shopping("juice price", gl="ae")
    assert calls[0]["gl"] == "ae"
    assert len(out) == 1                      # القائمة بلا سعر واضح أُسقطت
    v = out[0].value
    assert v["price"] == 12.0 and v["currency"] == "AED"
    assert v["price_raw"] == "AED 12.00" and v["store"] == "Carrefour UAE"
    assert v["link"] == "https://carrefouruae.com/x"


def test_web_search_shopping_no_key_is_declared_gap():
    import silk_websearch_agent as W
    with mock.patch.dict(os.environ, {}, clear=True):
        out = W.web_search_shopping("juice price", gl="ae")
    assert out[0].value is None and "SEARCH_API_KEY" in out[0].note


def test_web_search_shopping_empty_results_declared_not_fabricated():
    import silk_websearch_agent as W
    with mock.patch.dict(os.environ, {"SEARCH_API_KEY": "k"}), \
         mock.patch("requests.post", return_value=_resp({"shopping": []})):
        out = W.web_search_shopping("juice price", gl="ye")
    assert out[0].value is None and "no shopping results" in out[0].note


def test_web_search_shopping_all_unparseable_prices_declared_not_fabricated():
    import silk_websearch_agent as W
    with mock.patch.dict(os.environ, {"SEARCH_API_KEY": "k"}), \
         mock.patch("requests.post", return_value=_resp({"shopping": [
             {"title": "x", "price": "Call for price", "source": "s",
              "link": "l"}]})):
        out = W.web_search_shopping("juice price", gl="ye")
    assert out[0].value is None
    assert "no parseable price" in out[0].note


# ── التكامل: PricingAgent يستعمل Shopping عند غياب /deepen ──────────────────

def test_pricing_agent_falls_back_to_free_shopping_when_deepen_unavailable():
    import silk_research as R
    from conftest import block_network
    task = {"product": "عصير", "hs6": "200989", "iso3": "YEM", "m49": "887",
           "iso2": "ye", "market_name": "Yemen", "year": 2023}
    shopping = [__import__("silk_data_layer").DataPoint(
        {"title": "Juice 1L", "price": 3.5, "currency": "USD",
         "price_raw": "$3.50", "store": "example.com",
         "link": "https://example.com/p"},
        "Web Search (Serper Shopping)", 0.6, "listing", "2026-07-07")]
    with block_network(), \
         mock.patch("silk_websearch_agent.web_search_shopping",
                   return_value=shopping):
        out = R.PricingAgent().run(task).findings[0]
    f = next(x for x in out["findings"] if x["metric"] == "retail_prices")
    assert f["value"][0]["price"] == 3.5 and f["value"][0]["store"] == \
        "example.com"
    assert "Google Shopping" in f["note"]


def test_pricing_agent_no_paid_no_shopping_is_still_an_honest_gap():
    import silk_research as R
    from conftest import block_network
    task = {"product": "عصير", "hs6": "200989", "iso3": "YEM", "m49": "887",
           "iso2": "ye", "market_name": "Yemen", "year": 2023}
    with block_network(), \
         mock.patch.dict(os.environ, {"SEARCH_API_KEY": ""}):
        out = R.PricingAgent().run(task).findings[0]
    assert not any(f["metric"] == "retail_prices" for f in out["findings"])
    assert any("retail_prices" in g for g in out["gaps"])

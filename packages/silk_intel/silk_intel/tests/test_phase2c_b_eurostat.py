"""اختبارات المرحلة ٢ج — خيار B (تكامل يوروستات): حصة إنفاق الغذاء من مسح
ميزانية الأسرة، وعدد السكان المولودين خارج السوق — EU/EFTA حصراً، امتناع
معلن تلقائي بلا أي محاولة جلب خارجها. الشبكة مقطوعة/مموَّهة حيث يلزم.
Run:  python3 -m pytest tests/ -q
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network


def _ref(country):
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market(country)
    return ref


def _fake_response(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    if status >= 400:
        import requests
        r.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    return r


# ── نطاق التغطية (EU/EFTA فقط) ────────────────────────────────────────────

def test_eu_efta_market_list_shape():
    from silk_eurostat_agent import EU_EFTA_MARKETS
    assert "NLD" in EU_EFTA_MARKETS and "FRA" in EU_EFTA_MARKETS
    assert "CHE" in EU_EFTA_MARKETS  # EFTA
    assert "SAU" not in EU_EFTA_MARKETS and "USA" not in EU_EFTA_MARKETS
    assert "GBR" not in EU_EFTA_MARKETS  # خرجت من الاتحاد — ليست مؤهَّلة


def test_geo_code_greece_override():
    from silk_eurostat_agent import _geo_code
    assert _geo_code("GRC", "GR") == "EL"
    assert _geo_code("NLD", "NL") == "NL"


def test_non_eu_market_declines_without_any_http_attempt():
    from silk_eurostat_agent import household_food_expenditure_share
    with patch("silk_eurostat_agent.requests.get") as mocked:
        dp = household_food_expenditure_share("SAU", "SA")
    mocked.assert_not_called()
    assert dp.value is None and dp.confidence == 0.0
    assert "لا يغطي" in dp.note


def test_non_eu_market_foreign_born_declines_too():
    from silk_eurostat_agent import foreign_born_population_count
    with patch("silk_eurostat_agent.requests.get") as mocked:
        dp = foreign_born_population_count("USA", "US")
    mocked.assert_not_called()
    assert dp.value is None and dp.confidence == 0.0


# ── المسار الإيجابي (سوق مؤهَّل) ──────────────────────────────────────────

def test_household_expenditure_share_parses_dict_value():
    from silk_eurostat_agent import household_food_expenditure_share
    payload = {"value": {"0": 14.2}}
    with block_network(), patch("silk_eurostat_agent.requests.get",
                                return_value=_fake_response(payload)):
        dp = household_food_expenditure_share("NLD", "NL", 2020)
    assert dp.value == 14.2
    assert dp.source == "Eurostat (مسح ميزانية الأسرة)"
    assert dp.confidence == 0.75


def test_foreign_born_count_parses_list_value():
    from silk_eurostat_agent import foreign_born_population_count
    payload = {"value": [1_850_000]}
    with block_network(), patch("silk_eurostat_agent.requests.get",
                                return_value=_fake_response(payload)):
        dp = foreign_born_population_count("NLD", "NL", 2020)
    assert dp.value == 1_850_000.0
    assert dp.source == "Eurostat (إحصاءات الهجرة)"
    assert "نسبة المسلمين" in dp.note  # يوضّح أنه ليس بديلاً عنها


def test_no_year_uses_last_time_period():
    from silk_eurostat_agent import household_food_expenditure_share
    payload = {"value": {"0": 13.0}}
    with block_network(), patch("silk_eurostat_agent.requests.get",
                                return_value=_fake_response(payload)) as m:
        household_food_expenditure_share("NLD", "NL")
    params = m.call_args.kwargs.get("params") or m.call_args[1].get("params")
    assert params.get("lastTimePeriod") == 1
    assert "time" not in params


# ── لا اختلاق — كل مسار فشل يعيد None، لا صفراً ───────────────────────────

def test_fetch_failure_returns_none_not_zero():
    from silk_eurostat_agent import household_food_expenditure_share
    with block_network(), patch("silk_eurostat_agent.requests.get",
                                side_effect=OSError("network disabled")):
        dp = household_food_expenditure_share("NLD", "NL", 2020)
    assert dp.value is None and dp.confidence == 0.0


def test_http_error_status_returns_none():
    from silk_eurostat_agent import foreign_born_population_count
    with block_network(), patch("silk_eurostat_agent.requests.get",
                                return_value=_fake_response({}, status=404)):
        dp = foreign_born_population_count("NLD", "NL", 2020)
    assert dp.value is None and dp.confidence == 0.0


def test_malformed_payload_returns_none():
    from silk_eurostat_agent import household_food_expenditure_share
    with block_network(), patch("silk_eurostat_agent.requests.get",
                                return_value=_fake_response({"unexpected": 1})):
        dp = household_food_expenditure_share("NLD", "NL", 2020)
    assert dp.value is None and dp.confidence == 0.0


def test_empty_value_returns_none():
    from silk_eurostat_agent import household_food_expenditure_share
    with block_network(), patch("silk_eurostat_agent.requests.get",
                                return_value=_fake_response({"value": {}})):
        dp = household_food_expenditure_share("NLD", "NL", 2020)
    assert dp.value is None and dp.confidence == 0.0


# ── silk_llm_runtime._tool_eurostat_eu_signals ───────────────────────────

def test_tool_which_both_calls_both_signals():
    from silk_llm_runtime import _tool_eurostat_eu_signals
    market = _ref("Netherlands")
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}
    with patch("silk_eurostat_agent.household_food_expenditure_share") as h, \
         patch("silk_eurostat_agent.foreign_born_population_count") as f:
        from silk_data_layer import DataPoint
        h.return_value = DataPoint(14.0, "Eurostat (مسح ميزانية الأسرة)",
                                   0.75, "n", "2026-07-14")
        f.return_value = DataPoint(1_000_000.0, "Eurostat (إحصاءات الهجرة)",
                                   0.75, "n", "2026-07-14")
        out = _tool_eurostat_eu_signals({"which": "both"}, ctx)
    assert len(out) == 2
    h.assert_called_once()
    f.assert_called_once()


def test_tool_which_household_expenditure_only():
    from silk_llm_runtime import _tool_eurostat_eu_signals
    market = _ref("Netherlands")
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}
    with patch("silk_eurostat_agent.household_food_expenditure_share") as h, \
         patch("silk_eurostat_agent.foreign_born_population_count") as f:
        from silk_data_layer import DataPoint
        h.return_value = DataPoint(14.0, "s", 0.75, "n", "2026-07-14")
        out = _tool_eurostat_eu_signals({"which": "household_expenditure"}, ctx)
    assert len(out) == 1
    h.assert_called_once()
    f.assert_not_called()


def test_tool_non_eu_market_returns_declined_datapoints_no_http():
    from silk_llm_runtime import _tool_eurostat_eu_signals
    market = _ref("Nigeria")
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}
    with block_network(), patch("silk_eurostat_agent.requests.get") as mocked:
        out = _tool_eurostat_eu_signals({"which": "both"}, ctx)
    mocked.assert_not_called()
    assert all(dp.value is None for dp in out)


# ── تسجيل الأداة والبعثة ─────────────────────────────────────────────────

def test_tool_registered_in_tools_registry():
    from silk_llm_runtime import TOOLS
    assert "eurostat_eu_signals" in TOOLS
    assert TOOLS["eurostat_eu_signals"]["fn"].__name__ == "_tool_eurostat_eu_signals"


def test_consumer_culture_has_eurostat_tool_and_scoping_instruction():
    from silk_missions import MISSIONS
    m = MISSIONS["consumer_culture"]
    assert "eurostat_eu_signals" in m["allowed_tools"]
    assert "الاتحاد الأوروبي" in m["instructions"]
    assert "خارج أوروبا لا تستدعِ" in m["instructions"]

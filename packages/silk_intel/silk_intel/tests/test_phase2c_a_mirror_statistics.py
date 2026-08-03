"""اختبارات المرحلة ٢ج — خيار A (إحصاءات المرآة داخل comtrade_imports/
comtrade_competitors): حين تعذّر الاستعلام المباشر (السوق لا تُبلِغ
كومتريد عن نفسها)، احتياط يسأل الشركاء التجاريين "كم صدّرتم لهذه
السوق؟" — موسوم دوماً بمصدر/ثقة/ملاحظة مختلفة عن التقرير المباشر، ولا
يُستدعى إطلاقاً عند فشل الجلب الفعلي (شبكة/429)، فقط عند ردّ ناجح فارغ.
الشبكة مقطوعة حيث يلزم.
Run:  python3 -m pytest tests/ -q
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network


def _ref():
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Nigeria")
    return ref


# ── silk_data_layer.comtrade_trade_mirror_total ─────────────────────────

def test_mirror_total_sums_partner_export_declarations():
    from silk_data_layer import comtrade_trade_mirror_total

    recs = [{"reporterCode": "156", "primaryValue": 4_000_000.0},
            {"reporterCode": "356", "primaryValue": 1_500_000.0}]
    with block_network(), patch("silk_data_layer.comtrade_trade",
                                return_value=recs) as m:
        total = comtrade_trade_mirror_total("080410", 566, 2023, flow="M")

    assert total == 5_500_000.0
    # الاتجاه معكوس (X بدل M) والشريك هو السوق، لا مفتاحاً عالمياً.
    args, kwargs = m.call_args
    assert kwargs.get("flow") == "X" or "X" in args
    assert kwargs.get("partner") == 566 or 566 in args


def test_mirror_total_never_fabricates_zero():
    from silk_data_layer import comtrade_trade_mirror_total
    with block_network(), patch("silk_data_layer.comtrade_trade",
                                return_value=[]):
        assert comtrade_trade_mirror_total("080410", 566, 2023) is None
    with block_network(), patch("silk_data_layer.comtrade_trade",
                                return_value=None):
        assert comtrade_trade_mirror_total("080410", 566, 2023) is None


# ── silk_data_layer_v2.market_competitors_mirror ────────────────────────

def test_market_competitors_mirror_aggregates_by_reporter():
    from silk_data_layer_v2 import market_competitors_mirror

    recs = [{"reporterCode": "156", "primaryValue": 3_000_000.0},
            {"reporterCode": "156", "primaryValue": 1_000_000.0},
            {"reporterCode": "356", "primaryValue": 1_000_000.0}]
    with block_network(), patch("silk_data_layer_v2.comtrade_trade",
                                return_value=recs):
        comps = market_competitors_mirror("080410", 566, 2023)

    assert len(comps) == 2
    assert comps[0].value["value_usd"] == 4_000_000.0  # China rows summed
    assert comps[0].source == "UN Comtrade (مرآة)"
    assert comps[0].confidence == 0.6
    assert "مرآة" in comps[0].note


def test_market_competitors_mirror_empty_on_no_records():
    from silk_data_layer_v2 import market_competitors_mirror
    with block_network(), patch("silk_data_layer_v2.comtrade_trade",
                                return_value=[]):
        assert market_competitors_mirror("080410", 566, 2023) == []


# ── silk_llm_runtime._tool_comtrade_imports ──────────────────────────────

def test_tool_comtrade_imports_uses_mirror_only_when_direct_is_empty():
    from silk_llm_runtime import _tool_comtrade_imports
    market = _ref()
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}

    with block_network(), \
         patch("silk_llm_runtime.comtrade_trade", return_value=[]), \
         patch("silk_llm_runtime.comtrade_trade_mirror_total",
              return_value=2_000_000.0) as mirror_fn:
        dps = _tool_comtrade_imports({"years": [2023]}, ctx)

    mirror_fn.assert_called_once()
    assert len(dps) == 1
    assert dps[0].value == 2_000_000.0
    assert dps[0].source == "UN Comtrade (مرآة)"
    assert dps[0].confidence == 0.6
    assert dps[0].status == "mirrored"


def test_tool_comtrade_imports_skips_mirror_when_direct_has_data():
    from silk_llm_runtime import _tool_comtrade_imports
    market = _ref()
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}
    recs = [{"partnerCode": "0", "primaryValue": 900_000.0}]  # لا netWgt

    with block_network(), \
         patch("silk_llm_runtime.comtrade_trade", return_value=recs), \
         patch("silk_llm_runtime.comtrade_trade_mirror_total") as mirror_fn:
        dps = _tool_comtrade_imports({"years": [2023]}, ctx)

    mirror_fn.assert_not_called()
    assert dps[0].value == 900_000.0
    assert dps[0].source == "UN Comtrade"


def test_tool_comtrade_imports_skips_mirror_on_fetch_failure():
    """فشل جلب فعلي (شبكة/429) لا يستدعي المرآة — إعادة محاولة بمعامل
    مختلف على نداء فاشل فعلياً لن تحلّ عطلاً حياً وتستهلك ميزانية كومتريد
    اليومية بلا داعٍ (تعليق التصميم في comtrade_trade_mirror_total)."""
    from silk_llm_runtime import _tool_comtrade_imports
    market = _ref()
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}

    with block_network(), \
         patch("silk_llm_runtime.comtrade_trade", return_value=None), \
         patch("silk_llm_runtime.comtrade_trade_mirror_total") as mirror_fn:
        dps = _tool_comtrade_imports({"years": [2023]}, ctx)

    mirror_fn.assert_not_called()
    assert dps[0].status == "fetch_failed"


def test_tool_comtrade_imports_declares_gap_when_mirror_also_empty():
    from silk_llm_runtime import _tool_comtrade_imports
    market = _ref()
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}

    with block_network(), \
         patch("silk_llm_runtime.comtrade_trade", return_value=[]), \
         patch("silk_llm_runtime.comtrade_trade_mirror_total",
              return_value=None):
        dps = _tool_comtrade_imports({"years": [2023]}, ctx)

    assert dps[0].value is None
    assert dps[0].status == "no_record"
    assert "مرآة" in dps[0].note


# ── silk_llm_runtime._tool_comtrade_competitors ──────────────────────────

def test_tool_comtrade_competitors_uses_mirror_only_when_direct_is_empty():
    from silk_llm_runtime import _tool_comtrade_competitors
    from silk_data_layer import DataPoint
    market = _ref()
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}
    mirror_dp = DataPoint({"partner": "China", "code": "156",
                          "value_usd": 4_000_000.0, "share": 100.0},
                         "UN Comtrade (مرآة)", 0.6, "مرآة", "2026-07-14")

    with block_network(), \
         patch("silk_data_layer_v2.market_competitors", return_value=[]), \
         patch("silk_data_layer_v2.market_competitors_mirror",
              return_value=[mirror_dp]):
        dps = _tool_comtrade_competitors({}, ctx)

    summary = dps[0]
    assert summary.source == "UN Comtrade (مرآة)"
    assert summary.confidence == 0.6
    assert "مرآة" in summary.note


def test_tool_comtrade_competitors_skips_mirror_when_direct_has_data():
    from silk_llm_runtime import _tool_comtrade_competitors
    from silk_data_layer import DataPoint
    market = _ref()
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}
    direct_dp = DataPoint({"partner": "China", "code": "156",
                          "value_usd": 4_000_000.0, "share": 100.0},
                         "UN Comtrade", 0.9, "n", "2026-07-14")

    with block_network(), \
         patch("silk_data_layer_v2.market_competitors",
              return_value=[direct_dp]), \
         patch("silk_data_layer_v2.market_competitors_mirror") as mirror_fn:
        dps = _tool_comtrade_competitors({}, ctx)

    mirror_fn.assert_not_called()
    assert dps[0].source == "UN Comtrade"
    assert dps[0].confidence == 0.9


def test_tool_comtrade_competitors_declares_gap_when_both_empty():
    from silk_llm_runtime import _tool_comtrade_competitors
    market = _ref()
    ctx = {"market": market, "hs_code": "080410", "product": "تمور",
          "extra_findings": [], "extra_context": ""}

    with block_network(), \
         patch("silk_data_layer_v2.market_competitors", return_value=[]), \
         patch("silk_data_layer_v2.market_competitors_mirror",
              return_value=[]):
        dps = _tool_comtrade_competitors({}, ctx)

    assert len(dps) == 1
    assert dps[0].value is None
    assert "ولا مرآة" in dps[0].note

"""اختبارات المرحلة ٢ب (برنامج تحسين جودة التقرير، خارج نظام «الموجات»
المرقّم بالمستودع): أربع ترقيات عمق للبعثات بعد تدقيق ساكن (٢أ) —
trade_flow (نافذة خمس سنوات صريحة + حذف ادّعاء الموسمية من بيانات سنوية)،
demographics_economy (مؤشر بنك دولي جديد لسدّ فجوة "نسبة الشباب" الميتة)،
pricing_scout (سعر استيراد مرجعي من كومتريد عبر حقل الوزن الصافي غير
المستغَلّ سابقاً)، customs_requirements (إعلان فجوة صريح لصفوف صفرية).
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


# ── ١) trade_flow ────────────────────────────────────────────────────────

def test_trade_flow_moved_to_deep_research_budget():
    from silk_missions import _budget_for, _MISSION_BUDGET, _DEEP_RESEARCH_MISSIONS
    assert "trade_flow" in _DEEP_RESEARCH_MISSIONS
    assert _budget_for("trade_flow")["tool_calls"] > _MISSION_BUDGET["tool_calls"]


def test_trade_flow_instructions_force_five_year_window_and_cagr():
    from silk_missions import MISSIONS
    txt = MISSIONS["trade_flow"]["instructions"]
    assert "خمس سنوات" in txt
    assert "years" in txt
    assert "CAGR" in txt
    # بلاغ التدقيق (٢أ): بيانات كومتريد هنا سنوية إجمالية — لا تكشف موسمية
    # داخل السنة إطلاقاً؛ الطلب السابق باستنتاج موسمية من هذه الأرقام
    # استُبدل بمنع صريح بدل أن يُترك مجالاً مفتوحاً لادّعاء غير مسنود.
    assert "لا ادّعاء موسمية" in txt


# ── ٢) demographics_economy ──────────────────────────────────────────────

def test_demographics_economy_youth_indicator_wired():
    from silk_llm_runtime import _WB_INDICATORS
    assert _WB_INDICATORS.get("youth_population_pct") == "SP.POP.1564.TO.ZS"


def test_demographics_economy_instructions_unchanged_by_owner_decision():
    from silk_missions import MISSIONS
    txt = MISSIONS["demographics_economy"]["instructions"]
    assert "نسبة الشباب" in txt


# ── ٣) pricing_scout + comtrade unit-value ───────────────────────────────

def test_pricing_scout_has_comtrade_imports_tool():
    from silk_missions import MISSIONS
    assert "comtrade_imports" in MISSIONS["pricing_scout"]["allowed_tools"]


def test_pricing_scout_instructions_frame_unit_value_as_reference_not_retail():
    from silk_missions import MISSIONS
    txt = MISSIONS["pricing_scout"]["instructions"]
    # تمرير النثر (R1): الوسم أُعيدت صياغته إلى «متوسط سعر الاستيراد الرسمي
    # (UN Comtrade)» — يبقى مؤطَّراً كمرجع لا سعر تجزئة.
    assert "متوسط سعر الاستيراد الرسمي" in txt
    assert "لا سعر تجزئة فعلياً" in txt


def test_primary_qty_extracts_net_weight():
    from silk_data_layer import primary_qty
    assert primary_qty({"netWgt": 1250.0}) == 1250.0
    assert primary_qty({"netWgt": "980"}) == 980.0


def test_primary_qty_never_fabricates_zero_or_negative():
    from silk_data_layer import primary_qty
    # سجل ناقص/مشوّه (بلا وزن، أو وزن صفري/سالب/غير رقمي) يعيد None لا
    # صفراً — نفس مبدأ primary_value: يُسقِطه المستهلك ولا يقسم عليه.
    assert primary_qty({}) is None
    assert primary_qty({"netWgt": None}) is None
    assert primary_qty({"netWgt": 0}) is None
    assert primary_qty({"netWgt": -5}) is None
    assert primary_qty({"netWgt": "n/a"}) is None
    assert primary_qty({"netWgt": True}) is None


def test_tool_comtrade_imports_emits_unit_value_when_weight_present():
    from silk_llm_runtime import _tool_comtrade_imports
    from silk_market_resolver import MarketRef

    market = _ref()
    recs = [{"partnerCode": "0", "primaryValue": 1_000_000.0, "netWgt": 200_000.0}]
    with block_network(), \
         patch("silk_llm_runtime.comtrade_trade", return_value=recs):
        dps = _tool_comtrade_imports({"years": [2023]}, {
            "market": market, "hs_code": "080410", "product": "تمور",
            "extra_findings": [], "extra_context": ""})

    values = {round(dp.value, 2) for dp in dps if isinstance(dp.value, (int, float))}
    assert 1_000_000.0 in values
    assert 5.0 in values  # 1,000,000 / 200,000 = 5.0 $/kg
    unit_dp = next(dp for dp in dps if dp.value == 5.0)
    assert unit_dp.source == "UN Comtrade"
    assert "جملة" in unit_dp.note
    assert unit_dp.confidence < 0.9  # أدنى من ثقة إجمالي الاستيراد (0.9)


def test_tool_comtrade_imports_no_unit_value_without_weight():
    from silk_llm_runtime import _tool_comtrade_imports

    market = _ref()
    recs = [{"partnerCode": "0", "primaryValue": 1_000_000.0}]  # لا netWgt
    with block_network(), \
         patch("silk_llm_runtime.comtrade_trade", return_value=recs):
        dps = _tool_comtrade_imports({"years": [2023]}, {
            "market": market, "hs_code": "080410", "product": "تمور",
            "extra_findings": [], "extra_context": ""})

    # HF4.4 (بلاغ قطر): بندان — إجمالي الاستيراد + فجوةُ وزنٍ **مصرَّحة** بدقّة
    # (المُبلِّغ لا يودع الوزن، لا «لم نطلبه»). لا سعرَ وحدةٍ مُختلَق من وزنٍ غائب.
    assert len(dps) == 2
    assert dps[0].value == 1_000_000.0
    gap = dps[1]
    assert gap.value is None and gap.status == "no_record"
    assert "لا يودع بيانات الوزن" in gap.note  # صياغةٌ صادقة: المصدرُ لا المستهلك


# ── ٤) customs_requirements ──────────────────────────────────────────────

def test_customs_requirements_declares_zero_row_gap_explicitly():
    from silk_missions import MISSIONS
    txt = MISSIONS["customs_requirements"]["instructions"]
    assert "صفراً من الصفوف" in txt
    assert "أعلن الفجوة صراحة" in txt

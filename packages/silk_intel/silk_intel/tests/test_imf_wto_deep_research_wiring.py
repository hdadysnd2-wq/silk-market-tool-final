"""قفل توصيل IMF WEO + WTO TTD على مسار البحث العميق — hermetic wiring lock.

> **البلاغ (قبول حي 2026-07-20).** المسح السريع `/analyze` لم يستدعِ IMF — وهذا
> **صحيح**: IMF/WTO موصولان ببعثات `risk_news`/`demographics_economy`/
> `tariffs_agreements` التي تعمل في `/research` فقط. لكن ذلك يعني أن التكامل
> **لم يُثبَت أنه يخدم**. هذا القفل يثبت **التوصيل** هرمتياً (بلا نداء مدفوع):
> الأداة مُعلَنة للبعثة، ومُسجَّلة في السجلّ، ونداؤها يصل الوكيل الحقيقي —
> فلا ينكسر التوصيل بصمت. الخدمة الحيّة الفعلية تبقى تشغيلةَ المالك المدفوعة
> (قائمة التحقّق في docs/DECISIONS.md).

هرمتي: يقرأ MISSIONS/TOOLS ويُحاكي الوكلاء (imf_indicator/wto/wits) — لا شبكة.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_data_layer import DataPoint  # noqa: E402


class _Market:
    iso3 = "NLD"
    m49 = "528"
    iso2 = "NL"
    name_en = "Netherlands"
    name_ar = "هولندا"


# ─────────────── التوصيل: الأداة مُعلَنة للبعثة ومُسجَّلة ───────────────

def test_imf_tool_declared_to_deep_research_missions():
    """imf_indicator مُتاحة لبعثتَي المخاطر والاقتصاد الكلي (تعملان في /research)."""
    from silk_missions import MISSIONS
    assert "imf_indicator" in MISSIONS["demographics_economy"]["allowed_tools"]
    assert "imf_indicator" in MISSIONS["risk_news"]["allowed_tools"]


def test_wits_tariff_tool_declared_to_tariffs_mission():
    """wits_tariff (سلسلة WTO→WITS→فجوة) مُتاحة لبعثة التعريفات."""
    from silk_missions import MISSIONS
    assert "wits_tariff" in MISSIONS["tariffs_agreements"]["allowed_tools"]


def test_imf_and_wits_tools_registered_in_runtime():
    """كلا الأداتين مُسجَّلتان في سجلّ الأدوات بدالة التنفيذ الصحيحة."""
    from silk_llm_runtime import TOOLS, _tool_imf_indicator, _tool_wits_tariff
    assert TOOLS["imf_indicator"]["fn"] is _tool_imf_indicator
    assert TOOLS["wits_tariff"]["fn"] is _tool_wits_tariff


# ─────────────── التوصيل: نداء الأداة يصل الوكيل الحقيقي ───────────────

def test_imf_tool_call_reaches_imf_agent():
    """`_tool_imf_indicator` يستدعي `silk_imf_agent.imf_indicator` فعلاً ويمرّر
    السوق/المؤشّر/السنة — النتيجة DataPoint بمصدر IMF (محاكاة الوكيل، لا شبكة)."""
    import silk_imf_agent
    from silk_llm_runtime import _tool_imf_indicator
    fake = DataPoint(2.4, "IMF WEO", 0.9, "نمو الناتج الحقيقي 2024", "2026-07-20",
                     data_year=2024)
    with mock.patch.object(silk_imf_agent, "imf_indicator",
                           return_value=fake) as m:
        out = _tool_imf_indicator({"indicator": "real_gdp_growth", "year": 2024},
                                  {"market": _Market(), "hs_code": "080410"})
    assert m.called and m.call_args[0][0] == "NLD"       # وصل الوكيل بالسوق
    assert out and out[0].source == "IMF WEO" and out[0].value == 2.4


def test_wits_tariff_tool_prefers_wto_then_wits_then_gap():
    """`_tool_wits_tariff` → سلسلة WTO TTD → WITS → فجوة معلنة:
    (أ) WTO يعيد قيمة => يُخدَم WTO ولا يُستدعى WITS؛ (ب) WTO فارغ + WITS قيمة
    => يُخدَم WITS؛ (ج) كلاهما فارغ => فجوة معلنة (value=None) لا اختلاق."""
    import silk_tariffs_agent as T
    from silk_llm_runtime import _tool_wits_tariff
    ctx = {"market": _Market(), "hs_code": "080410"}

    # (أ) WTO يخدم أولاً — WITS لا يُستدعى.
    wto_val = DataPoint(3.5, "WTO TTD", 0.9, "تعريفة مطبّقة", "2026-07-20")
    with mock.patch("silk_wto_tariff.wto_applied_tariff", return_value=wto_val), \
         mock.patch.object(T, "applied_tariff") as wits_spy:
        out = _tool_wits_tariff({"partner_iso3": "SAU"}, ctx)
    assert out[0].source == "WTO TTD" and out[0].value == 3.5
    assert not wits_spy.called, "WITS استُدعي رغم نجاح WTO (السلسلة مكسورة)"

    # (ب) WTO فارغ => WITS يخدم.
    wto_gap = DataPoint(None, "WTO TTD", 0.0, "لا مفتاح WTO", "2026-07-20")
    wits_val = DataPoint(5.0, "World Bank WITS", 0.9, "تعريفة WITS", "2026-07-20")
    with mock.patch("silk_wto_tariff.wto_applied_tariff", return_value=wto_gap), \
         mock.patch.object(T, "applied_tariff", return_value=wits_val):
        out = _tool_wits_tariff({"partner_iso3": "SAU"}, ctx)
    assert out[0].source == "World Bank WITS" and out[0].value == 5.0

    # (ج) كلاهما فارغ => فجوة معلنة، لا اختلاق.
    with mock.patch("silk_wto_tariff.wto_applied_tariff", return_value=wto_gap), \
         mock.patch.object(T, "applied_tariff",
                           return_value=DataPoint(None, "World Bank WITS", 0.0,
                                                  "لا صفوف", "2026-07-20")):
        out = _tool_wits_tariff({"partner_iso3": "SAU"}, ctx)
    assert out[0].value is None and out[0].confidence == 0.0

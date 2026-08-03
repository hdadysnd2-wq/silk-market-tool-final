"""توجيه المالك «كلاهما»: (أ) ترقية المخاطر من بوابةٍ إلى عمودٍ خامسٍ موزون،
(ب) إضافة وكيل اللوجستيات الثامن (زمن التوريد + جسر التكلفة حتى الوصول المدفوع).

يقفل: العمود الخامس يُحسب ويؤثّر في الدرجة مع بقاء بوابة الخطر الحرج؛ ووكيل
اللوجستيات يرصد مؤشرات LPI/زمن الحدود الحقيقية ويُعلن سعرَ الشحن والتكلفةَ حتى
الوصول فجوةً موجَّهةً للطبقة المدفوعة — لا رقمَ شحنٍ مخترَع (المبدأ التأسيسي).
"""
import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402
import silk_decision as D  # noqa: E402
import silk_research as R  # noqa: E402
import silk_store  # noqa: E402

TASK = {"product": "تمور", "hs6": "080410", "iso3": "CHN", "m49": "156",
        "iso2": "CN", "market_name": "China", "year": 2023}


@contextlib.contextmanager
def _store(**inds):
    """مخزن مؤقّت مبذور بمؤشرات LPI/زمن الحدود — hermetic indicator store."""
    saved = silk_store._DEFAULT_PATH
    import tempfile
    silk_store._DEFAULT_PATH = os.path.join(tempfile.mkdtemp(), "s.db")
    try:
        silk_store.migrate()
        for ind, val in inds.items():
            silk_store.upsert_indicator("CHN", ind, 2022, val, "World Bank",
                                        0.9, "seed")
        yield
    finally:
        silk_store._DEFAULT_PATH = saved


# ── (أ) المخاطر عمودٌ خامسٌ موزون ────────────────────────────────────────────

def test_risk_is_a_weighted_fifth_pillar():
    assert "risk" in D.WEIGHT_OPTIONS["A"] and "risk" in D.WEIGHT_OPTIONS["B"]
    assert abs(sum(D.WEIGHT_OPTIONS["A"].values()) - 1.0) < 1e-9
    assert D._N_PILLARS == 5


def test_risk_pillar_computed_and_moves_the_score():
    """العمود يُحسب من WGI/LPI/الصرف، وخفضُ الأمان يخفض الدرجة تناسبيًّا."""
    base = {"coverage": 0.85, "pillar_inputs": {
        "market_attractiveness": {"tam_usd": 2.9e8, "import_cagr_pct": 12.0,
                                  "gdp_per_capita_usd": 40_000,
                                  "saudi_share_pct": 6.0},
        "competition_intensity": {"hhi": 0.15, "top_supplier_share_pct": 25.0,
                                  "named_company_count": 6},
        "regulatory_fit": {"tariff_applied_pct": 3.0,
                           "entry_requirements_count": 8,
                           "eligibility_gate": False},
        "profitability": {"border_unit_value_usd_kg": 3.4,
                          "saudi_border_unit_value_usd_kg": 3.0,
                          "margin_at_border_pct": 16.0},
        "risk": {"political_stability_wgi": 1.0, "regulatory_quality_wgi": 1.0,
                 "logistics_lpi": 4.0, "fx_volatility_pct": 1.0,
                 "critical_risk": False}}}
    d_safe = D.decide(base)
    assert d_safe["pillars"]["risk"]["value"] is not None
    assert d_safe["pillars"]["risk"]["value"] > 0.6      # سوق آمن
    # اخفض الأمان (بلد غير مستقرّ، لوجستيات ضعيفة، صرف متقلّب) دون بوابة حرجة
    import copy
    unsafe = copy.deepcopy(base)
    unsafe["pillar_inputs"]["risk"] = {
        "political_stability_wgi": -1.0, "regulatory_quality_wgi": -1.0,
        "logistics_lpi": 1.5, "fx_volatility_pct": 18.0, "critical_risk": False}
    d_unsafe = D.decide(unsafe)
    assert d_unsafe["pillars"]["risk"]["value"] < 0.4
    assert d_unsafe["score"] < d_safe["score"]           # المخاطر أثّرت في المجموع
    assert any("أمان السوق" in c for c in d_unsafe["conditions"])


def test_critical_risk_gate_survives_alongside_the_pillar():
    """البوابة والعمود معًا: خطرٌ حرجٌ يقلب NO-GO فوق العمود لا بدلاً منه."""
    crit = {"coverage": 0.85, "pillar_inputs": {
        "market_attractiveness": {"tam_usd": 2.9e8, "import_cagr_pct": 20.0,
                                  "gdp_per_capita_usd": 48_000,
                                  "saudi_share_pct": 8.0},
        "competition_intensity": {"hhi": 0.12, "top_supplier_share_pct": 20.0,
                                  "named_company_count": 8},
        "regulatory_fit": {"tariff_applied_pct": 0.0,
                           "entry_requirements_count": 9,
                           "eligibility_gate": False},
        "profitability": {"border_unit_value_usd_kg": 3.4,
                          "saudi_border_unit_value_usd_kg": 3.1,
                          "margin_at_border_pct": 18.0},
        "risk": {"political_stability_wgi": 0.9, "critical_risk": True}}}
    d = D.decide(crit)
    assert d["verdict"] == "NO-GO" and d["critical_risk"] is True
    assert d["pillars"]["risk"]["value"] is not None     # العمود لا يزال محسوباً


# ── (ب) وكيل اللوجستيات الثامن ───────────────────────────────────────────────

def test_logistics_agent_registered_eighth_and_free():
    assert R.LogisticsAgent in R.ALL_AGENTS
    assert R.LogisticsAgent.AGENT == "logistics"
    assert R.LogisticsAgent.PAID is False


def test_logistics_observes_lpi_and_bridges_freight_to_paid_layer():
    """مع مؤشرات LPI/زمن الحدود المبذورة: تُرصد بمصدرها؛ وسعرُ الشحن والتكلفةُ
    حتى الوصول يبقيان فجوةً موجَّهةً للطبقة المدفوعة — لا رقمَ مخترَع."""
    with _store(**{"LP.LPI.TIME.XQ": 3.6, "LP.LPI.ITRN.XQ": 3.4,
                   "IC.IMP.TMBC": 48.0}):
        with block_network():
            out = R.LogisticsAgent().run(dict(TASK)).findings[0]
    vals = {f["metric"]: f for f in out["findings"] if f["value"] is not None}
    assert vals["lpi_timeliness"]["value"] == 3.6
    assert vals["lpi_intl_shipments"]["value"] == 3.4
    # زمن التوريد = زمن امتثال الحدود ÷ 24، معلَّمٌ modeled بمعادلته
    assert vals["lead_time_days"]["value"] == 2.0 and vals["lead_time_days"]["modeled"]
    # سعر الشحن والتكلفة حتى الوصول: فجوةٌ صريحةٌ للطبقة المدفوعة (لا اختلاق)
    gap_text = " ".join(out["gaps"])
    assert "freight_cost_usd_kg" in gap_text and "Volza" in gap_text
    assert "landed_cost_usd_kg" in gap_text
    assert "freight_cost_usd_kg" not in vals   # لم يُرصد رقمٌ للشحن أبداً


def test_logistics_all_gaps_offline_never_fabricates():
    with block_network():
        out = R.LogisticsAgent().run(dict(TASK)).findings[0]
    # بلا مخزن ولا شبكة: كل المؤشرات فجوات معلنة، ولا قيمة مخترعة
    observed = [f for f in out["findings"] if f["value"] is not None]
    assert observed == [] or all(f["metric"] != "freight_cost_usd_kg"
                                 for f in observed)
    assert out["status"] == "failed" or out["gaps"]

"""اختبارات P0 (مواصفة المالك: إصلاحات ما قبل طبقة السرد) — wiring & confidence.

يقفل ثلاثة إصلاحات:
  (١) P0-1: سطر «لماذا» في القرار الشرطي يسرد الأسباب المتحقّقة حصراً — القالب
      القديم طبع «الثقة 0.91 دون 0.6» وهي ليست دونها، فقرأه المالك تناقضَ
      أرقام ثقة بين المشتقات.
  (٢) P0-3: كل صف مرتَّب يحمل iso2 — كان غائباً من طبقة بايثون كلياً فقاس
      وكيل Trends الاهتمام عالمياً بدل السوق المستهدف (تجويع مفاتيح صامت).
  (٣) P0-3: عقد مفاتيح المهمة — الوكلاء الثلاثة الأساسيون يعيدون نتائج حقيقية
      حين تتوافر البيانات بنفس مفاتيح مهمة المحرّك حرفياً (لا وكيل يُجوَّع).
Run:  python3 -m pytest tests/test_p0_wiring_and_confidence.py -q
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

from silk_data_layer import DataPoint, _today  # noqa: E402


# ── (١) لماذا القرار الشرطي — أسباب متحقّقة فقط ─────────────────────────────

def _bundle(coverage: float) -> dict:
    """حزمة §4b دنيا: عمود سوق قوي وحده — بقية الأعمدة غائبة (شروط مفتوحة)."""
    return {"coverage": coverage,
            "pillar_inputs": {"market_attractiveness": {
                "tam_usd": 5.0e7, "import_cagr_pct": 12.0}}}


def test_conditional_go_why_lists_only_true_reasons():
    import silk_decision as D
    d = D.decide(_bundle(coverage=1.0))
    assert d["verdict"] == "CONDITIONAL-GO"
    why = d["why"]
    # الثقة هنا 0.2 (تغطية 1.0 × عمود واحد من 5) — دون 0.6 فعلاً، فذكرها صادق.
    # (إصلاح تسريب السباكة: تُذكر بصيغة بشرية confidence_phrase لا كسراً
    # عشرياً خاماً — راجع tests/test_report_plumbing_leaks.py)
    from silk_narrative import confidence_phrase
    assert d["confidence"] < 0.6
    assert f"الثقة {confidence_phrase(d['confidence'])}" in why
    # score عمود السوق وحده مرتفع (≥ 0.65) — «النطاق الشرطي» ادعاء كاذب فلا يُطبع.
    if d["score"] >= 0.65:
        assert "النطاق الشرطي" not in why
    assert "شروط مفتوحة" in why            # شروط غائبة فعلاً => سبب صادق


def test_conditional_go_why_never_claims_high_confidence_is_low():
    """الحالة التي أبلغ عنها المالك: ثقة عالية مع شروط مفتوحة — لا يجوز أن
    يطبع «الثقة X دون 0.6» حين X ≥ 0.6. نبني قراراً ثقته مرتفعة اصطناعياً."""
    import silk_decision as D
    full = {"coverage": 1.0, "pillar_inputs": {
        "market_attractiveness": {"tam_usd": 5.0e7, "import_cagr_pct": 2.0},
        "competition_intensity": {"hhi": 0.5, "top_supplier_share_pct": 60.0},
        "regulatory_fit": {"requirements_count": 3},
        "profitability": {"margin_at_border_pct": 4.0},
        "risk": {"political_stability_wgi": 0.5}}}
    d = D.decide(full)
    if d["verdict"] == "CONDITIONAL-GO" and d["confidence"] >= 0.6:
        # الصيغة الجديدة البشرية أيضاً — لا سبب ثقة يُطبع حين الثقة كافية
        assert "الثقة" not in d["why"]


# ── (٢) iso2 على كل صف مرتَّب — يغذي Trends geo وبحث التسوّق gl ─────────────

def test_countries_list_is_unique_and_iso2_map_covers_it():
    import silk_market_ranker as R
    isos = [c["iso3"] for c in R.COUNTRIES]
    assert len(isos) == len(set(isos)), "duplicate market in COUNTRIES"
    missing = [i for i in isos if i not in R.ISO2]
    assert not missing, f"ISO2 map missing: {missing}"


def test_ranked_rows_carry_iso2_offline():
    import silk_market_ranker as R
    with block_network():
        rows = R.rank_markets("080410",
                              countries=[{"iso3": "ARE", "m49": "784"}],
                              year=2023)
    assert rows and rows[0]["iso3"] == "ARE"
    assert rows[0].get("iso2") == "AE"      # كان None قبل الإصلاح — تجويع صامت


# ── (٣) عقد مفاتيح المهمة — الوكلاء الأساسيون بنفس مفاتيح المحرّك حرفياً ─────

# نفس القاموس الذي يبنيه silk_engine.analyze (سطر 136-137) حرفاً بحرف.
ENGINE_TASK = {"hs_code": "080410", "market_m49": "784",
               "iso3": "ARE", "year": 2023}


def test_core_agents_return_findings_with_engine_task_keys():
    import silk_agents as A
    rec = [{"primaryValue": 1.5e6}]
    comp_dp = DataPoint(7.0e5, "UN Comtrade", 0.9, "partner X", _today())
    with mock.patch.object(A, "comtrade_trade", return_value=rec), \
         mock.patch.object(A, "gdp_per_capita",
                           return_value=DataPoint(43000.0, "World Bank", 0.9,
                                                  "GDP", _today())), \
         mock.patch.object(A, "ppp_per_capita",
                           return_value=DataPoint(60000.0, "World Bank", 0.9,
                                                  "PPP", _today())), \
         mock.patch.object(A, "population",
                           return_value=DataPoint(9.0e6, "World Bank", 0.9,
                                                  "pop", _today())), \
         mock.patch.object(A, "market_competitors", return_value=[comp_dp]):
        for agent_cls in (A.TradeFlowAgent, A.EconomicAgent,
                          A.CompetitionAgent):
            rep = agent_cls().run(dict(ENGINE_TASK))
            real = [f for f in rep.findings if f.value is not None]
            assert not rep.failed, (agent_cls.__name__, rep.summary)
            assert real, f"{agent_cls.__name__} starved of task keys"


def test_economic_agent_declares_missing_iso3_never_guesses():
    import silk_agents as A
    with block_network():
        rep = A.EconomicAgent().run({"hs_code": "080410",
                                     "market_m49": "784", "year": 2023})
    assert rep.failed and not [f for f in rep.findings if f.value is not None]
    assert "ISO3" in rep.summary

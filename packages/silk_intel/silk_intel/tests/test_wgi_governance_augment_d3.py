"""D3 (SPEC-v2) — أرقام WGI (استقرار سياسي/سيادة القانون/جودة التنظيم)
غائبة عن §9. السبب (تدقيق #1): بعثة risk_news تعتمد كلّياً على أن يستدعي
كلود أداة worldbank_indicator للمؤشرات الثلاثة — إن أغفل واحداً خرج §9
ناقصاً (خطأ ربط الكاتب/إظهار البعثة، لا خطأ جلب — الجلب مُصلَح ومقفول).

الإصلاح: جلب حتمي للمؤشرات الثلاثة يُلحَق بحقائق risk_news بعد تشغيلها —
حاضرة دائماً حين ينجح الجلب، فجوة معلنة (None، ثقة 0.0) حين يفشل. لا
اختلاق. يشمل RL.EST (سيادة القانون) الذي يغفله حتى RiskAgent في /analyze.

Run: python3 -m pytest tests/test_wgi_governance_augment_d3.py -q
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _no_network():
    """امنع أي جلب حيّ: cache miss + http يرمي — world_bank يعيد فجوة معلنة."""
    return [patch("silk_data_layer._cached_get", return_value=None),
            patch("silk_data_layer._http_get", side_effect=OSError("blocked")),
            patch("silk_store.get_indicator", return_value=None)]


def _blocked(fn):
    ctxs = _no_network()
    for c in ctxs:
        c.start()
    try:
        return fn()
    finally:
        for c in ctxs:
            c.stop()


def test_three_wgi_datapoints_declared_gap_when_offline_no_fabrication():
    """المؤشرات الثلاثة تعود فجوات معلنة (None، ثقة 0.0) بلا شبكة — لا صفر
    مختلق. الأسماء العربية الثلاثة كلها حاضرة."""
    import silk_missions as M
    dps = _blocked(lambda: M._wgi_governance_datapoints("NLD"))
    assert len(dps) == 3
    joined = " ".join(dp.note for dp in dps)
    for name in ("الاستقرار السياسي", "سيادة القانون", "جودة التنظيم"):
        assert name in joined, f"مؤشر مفقود: {name}"
    assert all(dp.value is None and dp.confidence == 0.0 for dp in dps)


def test_augment_attaches_three_risk_tagged_governance_findings():
    """الإلحاق يضيف ثلاثة بنود موسومة [risk] (كي يربطها كاتب §9) لبعثة بلا
    حقائق حوكمة — بما فيها RL.EST (سيادة القانون)."""
    import silk_missions as M
    from silk_agents import AgentReport
    rep = _blocked(lambda: M._augment_risk_news_wgi(
        AgentReport("LLMMissionAgent:risk_news", [], False, "مخاطر"), "NLD"))
    notes = [str(dp.note) for dp in rep.findings]
    joined = " ".join(notes)
    assert "PV.EST" in joined and "RL.EST" in joined and "RQ.EST" in joined
    assert all(n.startswith("[risk]") for n in notes)


def test_augment_does_not_duplicate_indicator_claude_already_surfaced():
    """إن رصد كلود PV.EST فعلاً، الإلحاق لا يكرّره — لكن يُكمل RL.EST/RQ.EST."""
    import silk_missions as M
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    pre = AgentReport(
        "LLMMissionAgent:risk_news",
        [DataPoint(0.42, "World Bank", 0.9,
                   "[risk] الاستقرار السياسي — PV.EST year=2023")],
        False, "مخاطر")
    rep = _blocked(lambda: M._augment_risk_news_wgi(pre, "NLD"))
    pv = [dp for dp in rep.findings if "PV.EST" in str(dp.note)]
    assert len(pv) == 1  # لا تكرار
    assert pv[0].value == 0.42  # بند كلود الأصلي محفوظ (لا استبدال)
    assert any("RL.EST" in str(dp.note) for dp in rep.findings)
    assert any("RQ.EST" in str(dp.note) for dp in rep.findings)


def test_augment_noop_without_iso3():
    """بلا iso3 لا إلحاق (لا كسر) — تحفّظ."""
    import silk_missions as M
    from silk_agents import AgentReport
    rep = M._augment_risk_news_wgi(
        AgentReport("LLMMissionAgent:risk_news", [], False, "x"), "")
    assert rep.findings == []


def test_wired_into_run_all_missions_deterministically():
    """تكامل: run_all_missions يُلحق WGI ببعثة risk_news حتماً (مسار resume
    الكامل — بلا نداء كلود جديد)."""
    import silk_missions as M
    from silk_agents import AgentReport
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Netherlands")
    resume = {k: AgentReport(f"m:{k}", [], False, "x") for k in M.MISSION_ORDER}
    reports = _blocked(lambda: M.run_all_missions(
        ref, "تمور", hs_code="080410", resume_reports=resume))
    rn = reports["risk_news"]
    joined = " ".join(str(dp.note) for dp in rn.findings)
    assert "PV.EST" in joined and "RL.EST" in joined and "RQ.EST" in joined

"""اختبارات Stage 3 — وكلاء البحث السبعة والمنسّق (§4b + توسعتا توجيه المالك).

تقفل البروتوكول الرباعي بنيوياً على الطبقة الجديدة كلها:
  (١) التصنيف: السبعة مجانية (PAID=False) — المدفوع محصور في /deepen.
  (٢) برهان عدائي: طبقة التجزئة المدفوعة (SerpApi) تُتخطى بنيوياً خارج /deepen
      بفجوة معلنة تشرح ذلك — بلا أي نداء.
  (٣) انحدار: مخطط §4b يرفض الرقم بلا مصدر والنموذج بلا معادلة؛ الرفض يُخفَّض
      إلى فجوة مسجَّلة لا يُبتلع.
  (٤) الفشل مرئي دائماً: خطأ وكيل/مهلة => مغلف failed بسببه؛ لا غياب صامت.
"""
import contextlib
import os
import sys
import tempfile
import time
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

import silk_research as R  # noqa: E402
import silk_store  # noqa: E402

TASK = {"product": "تمور", "hs6": "080410", "iso3": "CHN", "m49": "156",
        "iso2": "CN", "market_name": "China", "year": 2023,
        "product_card": None}


@contextlib.contextmanager
def _env(**kw):
    saved = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _seed_store():
    """بذور مخزن: ثلاث سنوات WLD (نمو) + شركاء 2023 بأوزان جزئية."""
    silk_store.migrate()
    rows = [
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2021, "flow": "M", "value_usd": 4.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2022, "flow": "M", "value_usd": 5.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 6.0e7, "qty_kg": 2.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "IRN",
         "year": 2023, "flow": "M", "value_usd": 3.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 1.8e7, "qty_kg": 8.0e6},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "TUN",
         "year": 2023, "flow": "M", "value_usd": 1.2e7},
    ]
    silk_store.upsert_trade_flows(rows)


def _out(agent_cls, task=None):
    rep = agent_cls().run(dict(task or TASK))
    return rep.findings[0]


# ── (١) التصنيف — البند الأول من البروتوكول ─────────────────────────────────

def test_all_eight_research_agents_are_free():
    assert len(R.ALL_AGENTS) == 8
    names = {c.AGENT for c in R.ALL_AGENTS}
    assert names == {"market_size", "competitor", "regulatory", "pricing",
                     "risk", "consumer_demand", "supplier", "logistics"}
    for cls in R.ALL_AGENTS:
        assert cls.PAID is False, cls.__name__


# ── (٣) مخطط §4b — الرقم بلا مصدر والنموذج بلا معادلة يُرفضان ───────────────

def test_schema_rejects_unsourced_value_and_formulaless_model():
    with pytest.raises(Exception):
        R.Finding(metric="x", value=5, sources=[])
    with pytest.raises(Exception):
        R.Finding(metric="x", value=5, modeled=True, formula=None,
                  sources=[R.SourceRef(source="S")])
    # الصحيحان يمرّان.
    R.Finding(metric="x", value=None, sources=[])
    R.Finding(metric="x", value=5, modeled=True, formula="x = a ÷ b",
              sources=[R.SourceRef(source="S")])


def test_invalid_finding_downgraded_to_logged_gap_not_swallowed():
    class _BadAgent(R.ResearchAgent):
        AGENT = "bad"
        EXPECTED = ("good",)

        def _research(self, task):
            return ([R._f("no_source", 5, []),                 # رقم بلا مصدر
                     R._f("good", 2, [R._src("Test Source")])], [])

    out = _out(_BadAgent)
    assert [f["metric"] for f in out["findings"]] == ["good"]
    assert any("no_source" in r for r in out["rejected"])
    assert any("no_source" in g for g in out["gaps"])          # فجوة، لا ابتلاع
    assert out["status"] == "partial" and out["coverage"] == 1.0


# ── (٤) المنسّق — فشل معلن غير محاجز + مهلة + سجل التشغيلات ─────────────────

def test_orchestrator_failure_is_visible_and_nonblocking_and_recorded():
    class _BoomAgent(R.ResearchAgent):
        AGENT = "boom"

        def _research(self, task):
            raise RuntimeError("boom!")

    class _OkAgent(R.ResearchAgent):
        AGENT = "ok"
        EXPECTED = ("x",)

        def _research(self, task):
            return [R._f("x", 1.0, [R._src("Test Source")])], []

    silk_store.migrate()
    bundle = R.ResearchOrchestrator(
        timeout=10, agent_classes=[_BoomAgent, _OkAgent]).run_market(dict(TASK))
    boom, ok = bundle["agents"]["boom"], bundle["agents"]["ok"]
    assert boom["status"] == "failed" and any("boom" in g for g in boom["gaps"])
    assert ok["status"] == "complete" and ok["coverage"] == 1.0
    assert bundle["coverage"] == 0.5
    with silk_store.connect() as conn:
        rows = conn.execute(
            "SELECT agent, status FROM agent_runs ORDER BY agent").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("boom", "failed"),
                                            ("ok", "complete")]


def test_orchestrator_timeout_becomes_declared_failure():
    class _SleepyAgent(R.ResearchAgent):
        AGENT = "sleepy"

        def _research(self, task):
            time.sleep(2.0)
            return [], []

    bundle = R.ResearchOrchestrator(
        timeout=0.2, agent_classes=[_SleepyAgent]).run_market(dict(TASK))
    out = bundle["agents"]["sleepy"]
    assert out["status"] == "failed"
    assert any("timeout" in g for g in out["gaps"])


# ── وكيل حجم السوق — TAM مرصود، SAM/SOM نموذجان معلنان ──────────────────────

def test_market_size_tam_growth_from_store_and_disclosed_models():
    _seed_store()
    with block_network():
        out = _out(R.MarketSizeAgent)
    vals = {f["metric"]: f for f in out["findings"] if f["value"] is not None}
    assert vals["tam_usd"]["value"] == 6.0e7
    assert vals["import_growth_pct"]["value"] == 50.0        # 4.0e7 → 6.0e7
    assert vals["import_cagr_pct"]["value"] == 22.5          # سنتان
    assert any("sam_usd" in g for g in out["gaps"])          # بلا بطاقة منتج
    # مع بطاقة منتج: نموذجان بمعادلة معلنة — وليسا رصداً.
    task2 = dict(TASK, product_card={"tier": "premium", "monthly_capacity": 1000,
                                     "unit": "kg", "cost_per_unit": 2.0})
    with block_network():
        out2 = _out(R.MarketSizeAgent, task2)
    v2 = {f["metric"]: f for f in out2["findings"] if f["value"] is not None}
    assert v2["sam_usd"]["value"] == round(6.0e7 * 0.2)
    assert v2["sam_usd"]["modeled"] and "SAM" in v2["sam_usd"]["formula"]
    assert v2["som_usd"]["value"] == 1000 * 12 * 3           # طاقة × سعر حدودي 3$
    assert v2["som_usd"]["modeled"] and "SOM" in v2["som_usd"]["formula"]


# ── وكيل المنافسة — طبقتان: دول (مرصودة) وشركات (فجوة معلنة بلا مفاتيح) ─────

def test_competitor_country_tier_observed_and_company_tier_gap_keyless():
    _seed_store()
    with _env(SEARCH_API_KEY=None, GOOGLE_MAPS_API_KEY=None):
        with block_network():
            out = _out(R.CompetitorAgent)
    vals = {f["metric"]: f for f in out["findings"] if f["value"] is not None}
    assert vals["hhi"]["value"] == 0.38                      # 0.25+0.09+0.04
    assert vals["top_supplier_share_pct"]["value"] == 50.0   # إيران
    assert vals["saudi_share_pct"]["value"] == 30.0
    assert len(vals["supplier_countries"]["value"]) == 3
    assert any("SEARCH_API_KEY" in g for g in out["gaps"])   # الطبقة الاسمية معلنة


# ── وكيل التسعير — حدودية مشتقة معلنة + تجزئة /deepen محجوبة بنيوياً ─────────

def test_pricing_border_unit_values_and_paid_retail_structurally_gated():
    _seed_store()
    # مفتاح SerpApi موجود عمداً — الحارس البنيوي (لا غياب المفتاح) هو المانع.
    with _env(SERPAPI_KEY="k", LOCALPRICE_API_KEY="k", SEARCH_API_KEY=None):
        with block_network():
            out = _out(R.PricingAgent)
    vals = {f["metric"]: f for f in out["findings"] if f["value"] is not None}
    b = vals["border_unit_value_usd_kg"]
    assert b["value"] == 3.0 and b["modeled"] and "÷" in b["formula"]
    s = vals["saudi_border_unit_value_usd_kg"]
    assert s["value"] == 2.25                                # 1.8e7 ÷ 8.0e6
    assert "retail_prices" not in vals                       # لا سعر مخترع
    assert any("deepen" in g for g in out["gaps"])           # البرهان العدائي (٢)
    # الهامش مع بطاقة منتج بوحدة kg — نموذج بمعادلة معلنة.
    task2 = dict(TASK, product_card={"unit": "kg", "cost_per_unit": 2.0,
                                     "shipping_per_unit": 0.5})
    with _env(SEARCH_API_KEY=None):
        with block_network():
            out2 = _out(R.PricingAgent, task2)
    v2 = {f["metric"]: f for f in out2["findings"] if f["value"] is not None}
    m = v2["margin_at_border_pct"]
    assert m["value"] == 16.7 and m["modeled"] and "الهامش" in m["formula"]


# ── وكيل المستهلك والطلب — مرجع Pew الساكن + قاعدة رمضان المعلنة ────────────

def test_consumer_demand_muslim_share_cited_and_ramadan_rule_disclosed():
    assert R.muslim_share("SAU")["pct"] == 93
    assert R.muslim_share("XKX") is None
    with block_network():
        out = _out(R.ConsumerDemandAgent)                    # CHN
    vals = {f["metric"]: f for f in out["findings"] if f["value"] is not None}
    ms = vals["muslim_share_pct"]
    assert ms["value"] == 2 and "pewresearch.org" in ms["sources"][0]["url"]
    rr = vals["ramadan_seasonality"]
    assert rr["modeled"] and "25%" in rr["formula"] and "محدود" in rr["value"]
    # سوق أغلبية: القاعدة تقلب الاستنتاج — والسوق المجهول فجوة معلنة.
    with block_network():
        out_sa = _out(R.ConsumerDemandAgent, dict(TASK, iso3="SAU", m49="682",
                                                  iso2="SA",
                                                  market_name="Saudi Arabia"))
    v_sa = {f["metric"]: f for f in out_sa["findings"] if f["value"] is not None}
    assert "مرجّحة" in v_sa["ramadan_seasonality"]["value"]
    with block_network():
        out_x = _out(R.ConsumerDemandAgent, dict(TASK, iso3="XKX", m49="0",
                                                 iso2="XK", market_name="Kosovo"))
    assert any("muslim_share_pct" in g for g in out_x["gaps"])


# ── وكيل المورّدين — بلا مفاتيح: فجوات معلنة، لا أسماء مخترعة ────────────────

def test_supplier_agent_declares_gaps_keyless_never_invents_names():
    with _env(SEARCH_API_KEY=None, GOOGLE_MAPS_API_KEY=None):
        with block_network():
            out = _out(R.SupplierAgent)
    assert out["status"] == "failed"
    assert not any(f["value"] is not None for f in out["findings"])
    assert any("saudi_suppliers" in g for g in out["gaps"])
    assert any("target_distributors" in g for g in out["gaps"])


# ── ربط المحرّك وسياسة الخادم ────────────────────────────────────────────────

def test_engine_attaches_full_bundle_and_server_policy_enables_research():
    import silk_engine
    with _env(SEARCH_API_KEY=None, GOOGLE_MAPS_API_KEY=None):
        with block_network():
            res = silk_engine.analyze(
                "تمور", countries=[{"iso3": "CHN", "m49": "156"}], year=2023,
                with_research=True)
    bundle = res["markets"][0]["research"]
    assert set(bundle["agents"]) == {c.AGENT for c in R.ALL_AGENTS}
    assert set(bundle["pillar_inputs"]) == {
        "market_attractiveness", "competition_intensity", "regulatory_fit",
        "profitability", "risk", "logistics"}
    # سياسة الخادم تفعّل الطبقة دون علم من العميل — نفس قفل Stage 2A.
    pytest.importorskip("fastapi"); pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import importlib
    import api
    with _env(SILK_API_KEY=None, SILK_RATE_LIMIT="0",
              SILK_STORE_DB=os.path.join(tempfile.mkdtemp(), "s.db")):
        importlib.reload(api)
        client = TestClient(api.create_app())
        captured = {}

        def spy(product, **kw):
            captured.update(kw)
            return {"product": product, "classified": False, "markets": [],
                    "hs_code": None, "hs_note": "x", "note": "x"}

        with mock.patch("silk_engine.analyze", spy):
            assert client.post("/analyze",
                               json={"product": "تمور"}).status_code == 200
        assert captured.get("with_research") is True


def test_pricing_section_coverage_reads_from_research_bundle():
    """بلاغ المالك («هل الوكلاء يعملون؟»): section_coverage.pricing كانت
    تعرض 0/0 دوماً على المسار المجاني رغم أن PricingAgent يحسب فعلاً قيمة
    الوحدة الحدودية من كومتريد (بلا حاجة لمفتاح مدفوع) — لأن silk_render لم
    يكن يقرأ من حزمة البحث row['research']['agents']['pricing'] لهذا
    القسم، بل من حقلَي prices/localprice وحدهما (طبقة التجزئة المدفوعة،
    فارغة بنيوياً خارج /deepen). يقفل هذا الاختبار إصلاح silk_render.py."""
    import silk_engine
    import silk_render
    _seed_store()
    with _env(SEARCH_API_KEY=None, GOOGLE_MAPS_API_KEY=None):
        with block_network():
            res = silk_engine.analyze(
                "تمور", countries=[{"iso3": "CHN", "m49": "156"}], year=2023,
                with_research=True)
    view = silk_render.build_view(res)
    cov = view["markets"][0]["section_coverage"]["pricing"]
    assert cov["attempted"] >= 1 and cov["contributed"] >= 1

"""أقفال تغطية العالم (الميزة أ) — Feature A: two-tier world coverage locks.

العائلة المحروسة: **tier2-fabrication** — أن تُنسَب قيمةٌ مختلَقة (اتفاقية/
لوجستيات/ثقافة، أو موقع سعودي/تركّز مورّدين) لسوقٍ من الفئة-٢ غير المنسَّقة.
العقد: الفئة-٢ تُسجَّل **حصراً** على بياناتٍ متاحةٍ عالمياً (إجمالي واردات من
نداء العالم الواحد + دخل/سكان البنك الدولي)؛ كل ما عداه فجوةٌ معلنة لا صفر
مختلَق. هذا الملف يقفل: (١) فصل الفئتين ووسومهما، (٢) صفر قيمة محلية للفئة-٢،
(٣) صفر نداء كومتريد إضافي للفئة-٢، (٤) التدهور عند نفاد الميزانية،
(٥) حتمية الترتيب على بيانات ثابتة، (٦) الافتراضي (الصمّام مُطفأ) بلا انحدار،
(٧) `/research` يقبل أيّ دولة ISO (كل countries.csv).
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402
import silk_market_ranker as R  # noqa: E402
from silk_data_layer import DataPoint  # noqa: E402


# ── تجهيزات ثابتة (fixtures) — 42 سوقاً عالمياً بقيمٍ تنازلية ثابتة ────────────
def _world_fixture(n: int = 42) -> list[dict]:
    """قائمة مستوردي العالم الثابتة — iso3 حقيقية، قيمٌ تنازلية حتمية."""
    isos = ["USA", "DEU", "GBR", "FRA", "ITA", "ESP", "NLD", "CAN", "CHN",
            "JPN", "KOR", "IND", "ARE", "SAU", "QAT", "KWT", "OMN", "BHR",
            "JOR", "EGY", "MAR", "TUN", "DZA", "TUR", "ZAF", "NGA", "KEN",
            "ETH", "GHA", "PAK", "BGD", "IDN", "MYS", "SGP", "THA", "VNM",
            # أسواق فئة-٢ نموذجية خارج القائمة المنسّقة (>38)
            "AGO", "ABW", "ALB", "AND", "ARM", "AUT", "AZE", "BEL"]
    isos = [i for i in isos if i != "SAU"][:n]   # السعودية منشأ لا سوق
    return [{"iso3": iso, "m49": f"{900 + i:03d}",
             "total_usd": float((n - i) * 1_000_000)}
            for i, iso in enumerate(isos)]


def _stub_income(iso3, year):
    return DataPoint(20000.0, "World Bank", 0.9, note="ppp stub",
                     retrieved_at="2024-01-01")


def _stub_pop(iso3, year):
    return DataPoint(10_000_000.0, "World Bank", 0.9, note="pop stub",
                     retrieved_at="2024-01-01")


def _stub_tier1(hs_code, c, year):
    """صفّ فئة-١ حتمي (بلا شبكة) — كل المكوّنات حاضرة بقيمٍ مشتقّة من iso3."""
    seed = float(sum(ord(x) for x in c["iso3"]))
    dp = lambda v, src="UN Comtrade": DataPoint(  # noqa: E731
        v, src, 0.9, note="tier1 stub", retrieved_at="2024-01-01")
    return {
        "iso3": c["iso3"], "m49": c["m49"], "iso2": R.ISO2.get(c["iso3"]),
        "components": {
            "market_size": dp(seed * 1000),
            "saudi_position": dp(3.0),
            "demand_capacity": dp(seed * 2, "World Bank"),
            "competition": dp(0.2),
        },
        "income_ppp": seed * 2, "population": 1_000_000.0,
        "year_used": year, "year_fell_back": False,
        "competitors": [], "top_competitor": None,
    }


@pytest.fixture
def world_env(monkeypatch):
    """بيئة تغطية العالم مع دوالّ مُثبَّتة (بلا شبكة، حتمية)."""
    monkeypatch.setattr(R, "world_import_totals",
                        lambda hs, y: _world_fixture())
    monkeypatch.setattr(R, "_income_dp", _stub_income)
    monkeypatch.setattr(R, "population", _stub_pop)
    monkeypatch.setattr(R, "_gather_row", _stub_tier1)
    monkeypatch.setattr(R, "_comtrade_budget_left", lambda: 999)
    return None


# ── (١) فصل الفئتين + الوسوم ─────────────────────────────────────────────────
def test_tier_separation_and_labels(world_env):
    ranked = R.rank_markets("100630", year=2022, world=True)
    tier1 = [r for r in ranked if r["tier"] == 1]
    tier2 = [r for r in ranked if r["tier"] == 2]
    assert len(tier1) == R._TIER1_N          # أعلى ٣٨ للفئة-١
    assert tier2, "يجب أن توجد صفوف فئة-٢ (بقية العالم)"
    # الفئة-١ كلها تسبق الفئة-٢ في الترتيب (العرض الافتراضي يبقى فئةً-١)
    tiers = [r["tier"] for r in ranked]
    assert tiers == sorted(tiers), "الفئة-١ يجب أن تسبق الفئة-٢ دائماً"
    # كل صفّ فئة-٢ يحمل الوسم التعاقدي الحرفي + سقف الثقة
    for r in tier2:
        assert r["coverage"] == R.TIER2_LABEL
        assert r["confidence"] <= R._TIER2_CONF_CAP


# ── (٢) صفر قيمة محلية للفئة-٢ (العقد المركزي) ───────────────────────────────
def test_tier2_never_carries_a_local_csv_value(world_env):
    ranked = R.rank_markets("100630", year=2022, world=True)
    tier2 = [r for r in ranked if r["tier"] == 2]
    assert tier2
    for r in tier2:
        comp = r["components"]
        # موقع السعودية والمنافسة = فجوتان معلنتان (لا صفر مختلَق)
        for gap_key in ("saudi_position", "competition"):
            dp = comp[gap_key]
            assert dp.value is None, f"{r['iso3']} {gap_key}: قيمة مختلَقة"
            assert dp.confidence == 0.0
            assert dp.status == "tier2_gap"
            assert R.TIER2_LABEL in dp.note
        # كل مصادر مكوّنات الفئة-٢ عالمية فقط — لا مصدر محلي (اتفاقيات/سكان محلي)
        sources = {dp.source for dp in comp.values()}
        assert sources <= {"UN Comtrade", "World Bank"}, sources
        # حجم السوق مشتقٌّ حرفياً من نداء العالم الواحد
        assert "نداء استيراد العالم الواحد" in comp["market_size"].note


def test_ranker_module_reads_no_local_market_csv():
    """حارس بنيوي: وحدة الترتيب لا تقرأ أيّ CSV محلّي (اتفاقيات/سكان/لغة/
    حصة مسلمين) — فمستحيلٌ بنيوياً أن تُنسَب قيمةٌ محلية لأيّ سوق (فئة-١ أو ٢)."""
    src = inspect.getsource(R)
    for forbidden in ("agreements_l1", "demographics_l1", "market_locale",
                      "muslim_share", "requirements_l1"):
        assert forbidden not in src, f"الترتيب يقرأ CSV محلّياً: {forbidden}"


# ── (٣) صفر نداء كومتريد إضافي للفئة-٢ (إثبات الميزانية) ──────────────────────
def test_tier2_gather_makes_zero_comtrade_calls(monkeypatch):
    """صفّ فئة-٢ يُبنى من `total_usd` (نداء العالم الواحد) + بنك دولي فقط —
    صفر نداء كومتريد لكل دولة. إثبات: الاستدعاء يُنجَح تحت حجب الشبكة الكامل
    ودالّة كومتريد الأساسية لا تُستدعى قطّ."""
    calls = []
    import silk_data_layer as dl

    def spy_comtrade(*a, **k):
        calls.append(a)
        raise AssertionError("الفئة-٢ استدعت كومتريد (يجب أن تكون صفراً)")

    monkeypatch.setattr(dl, "comtrade_trade", spy_comtrade)
    entry = {"iso3": "AGO", "m49": "024", "total_usd": 5_000_000.0}
    with block_network():
        row = R._tier2_gather_row("100630", entry, 2022)
    assert calls == []                            # صفر نداء كومتريد
    ms = row["components"]["market_size"]
    assert ms.value == 5_000_000.0                # من نداء العالم الواحد
    assert row["tier"] == 2 and row["coverage"] == R.TIER2_LABEL


# ── (٤) التدهور عند نفاد ميزانية كومتريد → الفئة-١ فقط ───────────────────────
def test_budget_exhausted_degrades_to_tier1_only(monkeypatch):
    """نفاد الميزانية => لا توسّع فئة-٢ إطلاقاً؛ نداء العالم لا يُجرى، ونتراجع
    للقائمة المنسّقة (فئة-١) — تدهور معلن، لا تلفيق جزئي."""
    world_totals = mock.Mock(side_effect=AssertionError(
        "world_import_totals لا يجب أن يُستدعى عند نفاد الميزانية"))
    monkeypatch.setattr(R, "world_import_totals", world_totals)
    monkeypatch.setattr(R, "_comtrade_budget_left", lambda: 0)
    monkeypatch.setattr(R, "top_import_markets", lambda hs, y: [])
    monkeypatch.setattr(R, "_gather_row", _stub_tier1)
    ranked = R.rank_markets("100630", year=2022, world=True)
    assert ranked, "يجب أن يبقى ترتيب فئة-١ المنسّق"
    assert all(r["tier"] == 1 for r in ranked)    # صفر فئة-٢
    world_totals.assert_not_called()


# ── (٥) حتمية الترتيب على بيانات ثابتة ───────────────────────────────────────
def test_ranking_is_deterministic_on_fixture(world_env):
    a = R.rank_markets("100630", year=2022, world=True)
    b = R.rank_markets("100630", year=2022, world=True)
    key = lambda ranked: [(r["iso3"], r["tier"], r["total_score"],  # noqa: E731
                           r["confidence"]) for r in ranked]
    assert key(a) == key(b)


# ── (٦) الصمّام مُطفأ (الافتراضي) => بلا انحدار، بلا فئة-٢ ───────────────────
def test_world_flag_off_is_todays_behavior(monkeypatch):
    """SILK_WORLD_MARKETS غير مضبوط => لا صفوف فئة-٢، والصفوف كلها فئة-١
    (حقلٌ إضافي غير مؤثِّر) — العرض كاليوم حرفياً."""
    monkeypatch.setattr(R, "_gather_row", _stub_tier1)
    monkeypatch.delenv("SILK_WORLD_MARKETS", raising=False)
    ranked = R.rank_markets("100630",
                            countries=[{"iso3": "ARE", "m49": "784"},
                                       {"iso3": "USA", "m49": "840"}],
                            year=2022)
    assert all(r["tier"] == 1 for r in ranked)
    assert not any("coverage" in r for r in ranked)


# ── (٧) /research يقبل أيّ دولة ISO — كل countries.csv (الميزة أ · بند ٢) ─────
def test_market_resolver_covers_every_world_country():
    """كل صفّ في data/countries.csv يُحَلّ عبر رمز ISO3 — لا تغطية منسّقة فقط.
    عيّنة فئة-٢ (أنغولا/أروبا/ألبانيا) تُحَلّ تماماً كأيّ سوق منسّق."""
    from silk_market_resolver import resolve_market, _load
    rows = _load()
    assert len(rows) > 200, "countries.csv يجب أن يغطّي كل دول العالم"
    for q, expect_iso in [("Angola", "AGO"), ("Aruba", "ABW"),
                          ("Albania", "ALB"), ("ABW", "ABW"),
                          ("نيجيريا", "NGA")]:
        ref, sug = resolve_market(q)
        assert ref is not None, f"{q}: لم يُحَلّ (اقتراحات {sug})"
        assert ref.iso3 == expect_iso


# ── (٨) /markets — منسدل الواجهة يكتسب مجموعة «كل دول العالم» عند التفعيل ─────
def test_markets_endpoint_world_grouping():
    """الصمّام مُطفأ => الرد فئة-١ فقط (كاليوم). مضبوطاً => يُلحَق بقية العالم
    كفئة-٢ موسومة، فيجمعها المنسدل تحت «كل دول العالم» — الافتراضي بلا انحدار."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import importlib
    import api as api_mod

    # مُطفأ: فئة-١ فقط
    if "SILK_WORLD_MARKETS" in os.environ:
        del os.environ["SILK_WORLD_MARKETS"]
    importlib.reload(api_mod)
    off = TestClient(api_mod.create_app()).get("/markets").json()
    assert off and all(m.get("tier", 1) == 1 for m in off)
    n_tier1 = len(off)

    # مُفعَّل: يُلحَق فئة-٢ موسومة، والفئة-١ تبقى كما هي عدداً
    os.environ["SILK_WORLD_MARKETS"] = "1"
    try:
        importlib.reload(api_mod)
        on = TestClient(api_mod.create_app()).get("/markets").json()
        t1 = [m for m in on if m.get("tier") == 1]
        t2 = [m for m in on if m.get("tier") == 2]
        assert len(t1) == n_tier1                 # الفئة-١ لم تتغيّر
        assert len(t2) > 100, "يجب إلحاق بقية دول العالم كفئة-٢"
        assert all(m.get("coverage") == R.TIER2_LABEL for m in t2)
        # لا تكرار iso3 عبر الفئتين
        isos = [m["iso3"] for m in on]
        assert len(isos) == len(set(isos))
    finally:
        del os.environ["SILK_WORLD_MARKETS"]
        importlib.reload(api_mod)

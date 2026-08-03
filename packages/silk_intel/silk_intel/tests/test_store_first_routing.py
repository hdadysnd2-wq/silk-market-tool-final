"""اختبارات التوجيه عبر المخزن أولاً — store-first routing for the core agents.

يقفل عقد «لا ندفع مرتين» على مسار الوكلاء الأساسيين (لا المُرتِّب وحده):
  • TradeFlowAgent: صف WLD مخزّن = صفر نداء خارجي، بإسناد «من المخزن» وتاريخ
    الجلب الأصلي؛ الغياب = مسار حي، ونجاح X يُكتب للمخزن (صف M العالمي لا
    يُكتب وحده — كان سيوهم قارئ المخزن بإجمالي بلا شركاء فيُسكِت وكيل المنافسة).
  • CompetitionAgent: يمرّ عبر market_imports_cached — شركاء مخزّنون يُخدمون
    بلا شبكة وبإسنادهم الأصلي.
  • mirror_saudi_export: صف X (reporter=SAU) مخزّن يُخدم بلا شبكة ويُكتب
    عابراً عند الجلب الحي الناجح.
المبدأ التأسيسي محفوظ: القيمة المخدومة من المخزن تحمل تاريخ جلبها الأصلي —
لا تُعرض كجلب حي اليوم؛ والمخزن الفارغ لا يُنتج قيماً.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402


def _seed_flows(rows):
    import silk_store
    silk_store.migrate()
    silk_store.upsert_trade_flows(rows)


# ── TradeFlowAgent ───────────────────────────────────────────────────────────

def test_tradeflow_serves_world_rows_from_store_without_network():
    _seed_flows([
        {"hs6": "040900", "reporter_iso3": "KWT", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 789206.0},
        {"hs6": "040900", "reporter_iso3": "KWT", "partner_iso3": "WLD",
         "year": 2023, "flow": "X", "value_usd": 12345.0},
    ])
    import silk_store
    stored = silk_store.get_trade_flow("040900", "KWT", "WLD", 2023, "M")
    from silk_agents import TradeFlowAgent
    with block_network():
        rep = TradeFlowAgent().run({"hs_code": "040900", "market_m49": "414",
                                    "iso3": "KWT", "year": 2023})
    real = [f for f in rep.findings if f.value is not None]
    assert sorted(f.value for f in real) == [12345.0, 789206.0]
    assert all("من المخزن" in f.note for f in real)
    assert all("مخزن الحقائق" in f.source for f in real)
    # تاريخ الجلب الأصلي محفوظ — لا خَتم بتاريخ القراءة كأنها جلب حي.
    assert all(f.retrieved_at == stored["retrieved_at"] for f in real)
    assert not rep.failed


def test_tradeflow_write_through_x_only_never_lone_world_m_row():
    """النجاح الحي يكتب صف X للمخزن؛ صف M العالمي لا يُكتب وحده (حارس التسميم)."""
    recs = [{"partnerCode": "0", "primaryValue": 5000.0}]
    import silk_agents
    with mock.patch.object(silk_agents, "comtrade_trade", return_value=recs):
        rep = silk_agents.TradeFlowAgent().run(
            {"hs_code": "040900", "market_m49": "504", "iso3": "MAR",
             "year": 2023})
    assert not rep.failed
    import silk_store
    assert silk_store.get_trade_flow("040900", "MAR", "WLD", 2023, "X") is not None
    assert silk_store.get_trade_flow("040900", "MAR", "WLD", 2023, "M") is None
    # الجولة الثانية: صف X من المخزن — نداء حي واحد فقط (لـ M الغائب).
    calls = {"n": 0}

    def counting(*a, **k):
        calls["n"] += 1
        return recs

    with mock.patch.object(silk_agents, "comtrade_trade", side_effect=counting):
        silk_agents.TradeFlowAgent().run(
            {"hs_code": "040900", "market_m49": "504", "iso3": "MAR",
             "year": 2023})
    assert calls["n"] == 1


def test_tradeflow_empty_store_offline_declares_gap_not_zero():
    """مخزن بارد + شبكة مقطوعة => تعذّر جلب معلن، لا صفر مختلق."""
    from silk_agents import TradeFlowAgent
    with block_network():
        rep = TradeFlowAgent().run({"hs_code": "040900", "market_m49": "414",
                                    "iso3": "KWT", "year": 2023})
    assert rep.failed
    assert all(f.value is None for f in rep.findings)
    assert all(f.status == "fetch_failed" for f in rep.findings)


# ── CompetitionAgent ─────────────────────────────────────────────────────────

def test_competition_serves_partners_from_store_without_network():
    _seed_flows([
        {"hs6": "040900", "reporter_iso3": "KWT", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 8102937.0},
        {"hs6": "040900", "reporter_iso3": "KWT", "partner_iso3": "DEU",
         "year": 2023, "flow": "M", "value_usd": 4000000.0},
    ])
    from silk_agents import CompetitionAgent
    with block_network():
        rep = CompetitionAgent().run({"hs_code": "040900", "market_m49": "414",
                                      "iso3": "KWT", "year": 2023})
    assert not rep.failed
    vals = [f.value for f in rep.findings]
    assert vals[0]["partner"] == "Saudi Arabia"
    assert vals[0]["value_usd"] == 8102937.0
    assert all("من المخزن" in f.note for f in rep.findings)
    assert all("مخزن الحقائق" in f.source for f in rep.findings)


def test_competition_cold_store_offline_fails_declared():
    from silk_agents import CompetitionAgent
    with block_network():
        rep = CompetitionAgent().run({"hs_code": "040900", "market_m49": "414",
                                      "iso3": "KWT", "year": 2023})
    assert rep.failed
    assert all(f.value is None for f in rep.findings)


# ── mirror_saudi_export ──────────────────────────────────────────────────────

def test_mirror_serves_from_store_without_network():
    _seed_flows([
        {"hs6": "040900", "reporter_iso3": "SAU", "partner_iso3": "DEU",
         "year": 2023, "flow": "X", "value_usd": 250000.0, "qty_kg": 50000.0},
    ])
    import silk_store
    stored = silk_store.get_trade_flow("040900", "SAU", "DEU", 2023, "X")
    from silk_data_layer_v2 import mirror_saudi_export
    with block_network():
        dp = mirror_saudi_export("040900", "276", "DEU", 2023)
    assert dp.value == {"value_usd": 250000.0, "qty_kg": 50000.0}
    assert "من المخزن" in dp.source and "من المخزن" in dp.note
    assert dp.retrieved_at == stored["retrieved_at"]


def test_mirror_write_through_then_store_hit():
    import silk_data_layer_v2 as v2
    recs = [{"partnerCode": "276", "primaryValue": 99000.0, "netWgt": 11000.0}]
    with mock.patch.object(v2, "comtrade_trade", return_value=recs):
        dp1 = v2.mirror_saudi_export("040900", "276", "DEU", 2023)
    assert dp1.value["value_usd"] == 99000.0
    import silk_store
    row = silk_store.get_trade_flow("040900", "SAU", "DEU", 2023, "X")
    assert row and row["value_usd"] == 99000.0 and row["qty_kg"] == 11000.0
    # الجولة الثانية بلا شبكة — من المخزن.
    with block_network():
        dp2 = v2.mirror_saudi_export("040900", "276", "DEU", 2023)
    assert dp2.value["value_usd"] == 99000.0
    assert "من المخزن" in dp2.note


def test_mirror_cold_store_offline_declares_absence():
    from silk_data_layer_v2 import mirror_saudi_export
    with block_network():
        dp = mirror_saudi_export("040900", "276", "DEU", 2023)
    assert dp.value is None and dp.confidence == 0.0


# ── مسار المُرتِّب · store hit keeps original fetch date ─────────────────────

def test_market_imports_cached_store_hit_keeps_original_fetch_date():
    _seed_flows([
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 900.0},
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 600.0},
    ])
    import silk_store
    stored = silk_store.get_trade_flow("080410", "ARE", "SAU", 2023, "M")
    import silk_data_layer_v2 as v2
    with block_network():
        got = v2.market_imports_cached("080410", "784", "ARE", 2023)
    assert got["served_from"] == "store"
    assert got["retrieved_at"] == stored["retrieved_at"]
    assert "من المخزن" in got["provenance_note"]
    comp = got["competitors"][0]
    assert comp.retrieved_at == stored["retrieved_at"]
    assert "من المخزن" in comp.note


# ── الدردشة · chat reads the STORED analysis, zero data fetches ─────────────

def test_chat_ask_reads_stored_analysis_with_zero_data_fetches(tmp_path,
                                                               monkeypatch):
    monkeypatch.setenv("SILK_DB", str(tmp_path / "silk.db"))
    monkeypatch.delenv("SILK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import silk_storage
    aid = silk_storage.save_analysis(
        {"product": "عسل", "hs_code": "040900", "year": 2023,
         "preliminary": True, "markets": []})
    import api
    from fastapi.testclient import TestClient
    client = TestClient(api.create_app())
    # أي جلب بيانات خارجي = فشل صريح — الدردشة تقرأ التحليل المخزّن فقط.
    with mock.patch("requests.get",
                    side_effect=AssertionError("chat must not re-fetch")), \
         mock.patch("requests.Session.get",
                    side_effect=AssertionError("chat must not re-fetch")):
        r = client.post(f"/analyses/{aid}/ask", json={"question": "كيف السوق؟"})
    assert r.status_code == 200
    body = r.json()
    # بلا مفتاح كلود: ملاحظة معلنة لا اختلاق — والأهم: صفر إعادة جلب.
    assert body.get("answer") is None and body.get("note")

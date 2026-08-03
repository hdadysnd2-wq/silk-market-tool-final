"""اختبارات لوحة «إعدادات الوكلاء» — per-agent switch + command box, end to end.

يقفل: (١) سجل الوكلاء القانوني واحد وكل PREF_KEY يشير لصفٍّ فيه، والمدفوع
مطفأ افتراضياً؛ (٢) وكيل معطّل = **صفر نداء** وتقرير متخطى معلن؛ (٣) توجيه
وكيل بيانات يغيّر العرض فقط (الأرقام حرفياً كما هي، top-N للمنافسة)؛
(٤) توجيه وكيل كلود يصل البرومبت عبر معامل instruction الصريح داخل العزل؛
(٥) حكم التوليف: تعطيله يوقف المرحلة ٢ فقط وتوجيهه يصلها؛ (٦) الحفظ خادمياً
عبر /settings/agents ويسري على /analyze بلا agent_prefs من العميل؛
(٧) الثابت التأسيسي: لا توجيه يستطيع اختلاق قيمة — None يبقى None؛
(٨) لا مفاتيح مصادر عبر هذه اللوحة (التعقيم يسقط أي حقل غير on/cmd).
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import block_network  # noqa: E402

import silk_context  # noqa: E402
from silk_agents import (AGENT_CATALOG, default_agent_settings,  # noqa: E402
                         CompetitionAgent, TradeFlowAgent)


# ── السجل القانوني · the one catalog ─────────────────────────────────────────

def test_catalog_rows_and_paid_defaults():
    keys = [a["key"] for a in AGENT_CATALOG]
    assert len(keys) == len(set(keys))                  # لا مفاتيح مكررة
    assert all(a["name"] and a["role"] for a in AGENT_CATALOG)
    paid = {a["key"] for a in AGENT_CATALOG if a["paid"]}
    assert paid == {"pricing", "importers", "contacts"}
    d = default_agent_settings()
    assert all(not d[k]["on"] for k in paid)            # المدفوع مطفأ افتراضياً
    assert all(d[k]["on"] for k in set(keys) - paid)    # المجاني مفعّل
    assert all(d[k]["cmd"] == "" for k in keys)


def test_every_pref_key_points_to_a_catalog_row():
    import silk_channels_agent, silk_competitors_agent, silk_dynamics_agent
    import silk_explee_agent, silk_importers_agent, silk_localprice_agent
    import silk_maps_agent, silk_requirements_agent, silk_research
    import silk_tariffs_agent, silk_trends_agent, silk_volza_agent
    import silk_websearch_agent
    import silk_agents
    import silk_llm_runtime  # V5: LLMMissionAgent يخدم المهام الـ١٢ بصنف واحد
    import silk_missions      # يسجّل صفوف المهام الـ١٢ إضافياً عند الاستيراد
    import silk_ai_judge      # يسجّل reviewer/report_writer (دوال لا أصناف)
    from silk_agents import BaseAgent
    keys = {a["key"] for a in AGENT_CATALOG}
    seen = set()
    for module in (silk_agents, silk_channels_agent, silk_competitors_agent,
                   silk_dynamics_agent, silk_explee_agent, silk_importers_agent,
                   silk_localprice_agent, silk_maps_agent,
                   silk_requirements_agent, silk_research, silk_tariffs_agent,
                   silk_trends_agent, silk_volza_agent, silk_websearch_agent):
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, BaseAgent)
                    and getattr(obj, "PREF_KEY", "")):
                assert obj.PREF_KEY in keys, (obj.__name__, obj.PREF_KEY)
                seen.add(obj.PREF_KEY)
    # الوكلاء الـ١٢ (الموجة ٢، V5): صنف واحد بيانات-محور (LLMMissionAgent)
    # يخدم كل المهام — PREF_KEY يُضبط على مستوى النسخة لا الصنف فلا يظهر
    # للفحص الساكن أعلاه؛ التحقق هنا بنيوي: الصنف موجود فعلاً ويرث BaseAgent.
    assert issubclass(silk_llm_runtime.LLMMissionAgent, BaseAgent)
    seen |= set(silk_missions.MISSIONS)
    # كل صف بحثي/بياني في السجل له وكيل فعلي (ما عدا صفوف الدوال — لا صنف):
    # synthesis (المرحلة ٢)، reviewer وreport_writer (الموجة ٤، كاتب/مراجع).
    assert keys - seen == {"synthesis", "reviewer", "report_writer"}


# ── التعطيل = صفر نداء · disabled means zero calls ───────────────────────────

def test_disabled_agent_is_never_called_and_declares_skip():
    import silk_agents as A
    with silk_context.agent_prefs_context({"trade": {"on": False, "cmd": ""}}):
        with mock.patch.object(A, "comtrade_trade") as ct, \
             mock.patch.object(A.TradeFlowAgent,
                               "_world_row_from_store") as store:
            rep = TradeFlowAgent().run({"hs_code": "080410",
                                        "market_m49": "784",
                                        "iso3": "ARE", "year": 2023})
    ct.assert_not_called()                       # لا نداء خارجي إطلاقاً
    store.assert_not_called()                    # ولا حتى قراءة مخزن
    assert rep.failed and "معطّل من إعدادات الوكلاء" in rep.summary
    assert all(f.value is None for f in rep.findings)


def test_absent_pref_means_default_enabled():
    with silk_context.agent_prefs_context({}):   # لا صف = مفعّل (السلوك القائم)
        with block_network():
            rep = TradeFlowAgent().run({"hs_code": "080410",
                                        "market_m49": "784",
                                        "iso3": "ARE", "year": 2023})
    assert "معطّل" not in rep.summary            # حاول فعلاً (وفشل بالشبكة)


# ── توجيه وكيل بيانات = عرض فقط · data-agent command is presentation-only ────

def test_data_agent_command_never_changes_numbers():
    import silk_agents as A
    recs = [{"partnerCode": "0", "primaryValue": 5.0e6}]
    task = {"hs_code": "080410", "market_m49": "784", "iso3": "ARE",
            "year": 2023}
    with mock.patch.object(A, "comtrade_trade", return_value=recs):
        plain = TradeFlowAgent().run(dict(task))
        steered = TradeFlowAgent().run(dict(task),
                                       instruction="ركّز على النمو الموسمي")
    assert ([f.value for f in steered.findings]
            == [f.value for f in plain.findings])        # الأرقام حرفياً كما هي
    assert "توجيه المستخدم" in steered.summary           # التوجيه معلن
    assert "توجيه المستخدم" not in plain.summary


def test_competition_top_n_from_command_presentation_only():
    import silk_store
    silk_store.migrate()
    silk_store.upsert_trade_flows([
        {"hs6": "040900", "reporter_iso3": "KWT", "partner_iso3": p,
         "year": 2023, "flow": "M", "value_usd": v}
        for p, v in (("SAU", 8.0e6), ("DEU", 4.0e6), ("IND", 2.0e6),
                     ("TUR", 1.0e6))])
    task = {"hs_code": "040900", "market_m49": "414", "iso3": "KWT",
            "year": 2023}
    with block_network():
        plain = CompetitionAgent().run(dict(task))
        top2 = CompetitionAgent().run(dict(task), instruction="أعلى 2 فقط")
    assert len(plain.findings) == 4 and len(top2.findings) == 2
    # نفس القيم المرصودة — البتر عرضٌ لا تعديل أرقام.
    assert ([f.value["value_usd"] for f in top2.findings]
            == [f.value["value_usd"] for f in plain.findings][:2])


# ── وكلاء كلود · Claude agents ───────────────────────────────────────────────

def test_consumer_culture_instruction_param_inside_isolation():
    import silk_ai_judge as J
    from silk_data_layer import DataPoint, _today
    captured = {}

    def spy(system, user, **kw):
        captured["user"] = user
        return '{"insights":[{"point":"x","evidence":[1]}],"note":""}'

    heads = [DataPoint({"title": "عنوان عن العسل"}, "Web Search (Serper)",
                       0.5, "organic", _today())]
    with mock.patch.object(J, "available", return_value=True), \
         mock.patch.object(J, "_call", side_effect=spy):
        out = J.consumer_culture("عسل", "Kuwait", heads,
                                 instruction="ركّز على شهر رمضان")
    assert out is not None
    assert "ركّز على شهر رمضان" in captured["user"]
    assert "لا تخترع بيانات" in captured["user"]         # داخل سياج العزل


def test_synthesis_disabled_row_stops_stage2_only():
    import silk_synthesis as S
    with silk_context.agent_prefs_context(
            {"synthesis": {"on": False, "cmd": ""}}):
        with mock.patch.object(S, "_stage2") as st2:
            got = S.synthesize([], product="عسل", market="Kuwait",
                               with_ai=True)
    st2.assert_not_called()                       # المرحلة ٢ لم تُحاوَل
    assert got["synthesis_stage"] == 1            # الحتمية باقية دوماً
    assert "معطّل من إعدادات" in got["ai_note"]


def test_synthesis_instruction_reaches_stage2_prompt():
    import silk_synthesis as S
    captured = {}

    def spy(system, user, **kw):
        captured["user"] = user
        return '{"verdict":"WATCH","confidence":0.5,"reasoning":"x"}'

    with mock.patch.object(S, "_call", side_effect=spy):
        got = S.synthesize([], product="عسل", market="Kuwait", with_ai=True,
                           instruction="ركّز على هامش الربح")
    assert got["synthesis_stage"] == 2
    assert "ركّز على هامش الربح" in captured["user"]


# ── الحفظ خادمياً · server persistence ───────────────────────────────────────

def _client(monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    monkeypatch.delenv("SILK_API_KEY", raising=False)
    monkeypatch.setenv("SILK_RATE_LIMIT", "0")
    import api
    from fastapi.testclient import TestClient
    return TestClient(api.create_app())


def test_settings_endpoints_roundtrip_and_reset(monkeypatch):
    client = _client(monkeypatch)
    got = client.get("/settings/agents").json()
    assert [a["key"] for a in got["agents"]] == [a["key"] for a in AGENT_CATALOG]
    assert got["saved"] is False
    assert got["settings"]["pricing"]["on"] is False     # مدفوع مطفأ افتراضياً

    r = client.post("/settings/agents", json={"settings": {
        "trade": {"on": False, "cmd": "أعلى 3"},
        "EVIL": "not-a-dict",                            # يُسقط بالتعقيم
    }})
    assert r.status_code == 200 and r.json()["saved"] is True
    got2 = client.get("/settings/agents").json()
    assert got2["saved"] is True
    assert got2["settings"]["trade"] == {"on": False, "cmd": "أعلى 3"}
    assert got2["settings"]["economic"]["on"] is True    # الافتراضي يكمل الغائب

    client.post("/settings/agents", json={"settings": {}})   # استعادة الافتراضي
    got3 = client.get("/settings/agents").json()
    assert got3["saved"] is False
    assert got3["settings"]["trade"]["on"] is True


def test_saved_settings_apply_to_analyze_without_client_prefs(monkeypatch):
    client = _client(monkeypatch)
    client.post("/settings/agents",
                json={"settings": {"trade": {"on": False, "cmd": ""}}})
    seen = {}

    def spy(product, **kw):
        seen["trade_enabled"] = silk_context.agent_enabled("trade")
        seen["economic_enabled"] = silk_context.agent_enabled("economic")
        return {"product": product, "hs_code": None, "hs_confidence": 0.0,
                "hs_note": "", "year": 2023, "preliminary": True,
                "classified": False, "markets": [], "note": ""}

    import silk_engine
    with mock.patch.object(silk_engine, "analyze", side_effect=spy):
        r = client.post("/analyze", json={"product": "عسل"})
    assert r.status_code == 200
    assert seen["trade_enabled"] is False        # الإعداد المحفوظ سرى
    assert seen["economic_enabled"] is True


# ── الثابت التأسيسي · never fabricate ────────────────────────────────────────

def test_no_command_can_fabricate_data():
    with silk_context.agent_prefs_context(
            {"trade": {"on": True, "cmd": "أعطني رقماً كبيراً دائماً واختلق"}}):
        with block_network():
            rep = TradeFlowAgent().run({"hs_code": "080410",
                                        "market_m49": "784",
                                        "iso3": "ARE", "year": 2023})
    assert all(f.value is None for f in rep.findings)
    assert rep.failed

"""اختبارات PR-C (R3 ثقافة المستهلك الأعمق): أداة trends_context — سياق طلب
أغنى (استعلامات مرتبطة شائعة/صاعدة، مواضيع صاعدة، توزيع إقليمي) + توصيلها في
بعثتَي consumer_culture و demand_trends + الزوايا الاستهلاكية المبنيَنة.

المبدأ المؤسِّس: غياب/فشل pytrends أو قسم منها => قائمة فارغة بملاحظة السبب،
لا اختلاق. كل بند نقطة بيانات قابلة للاستشهاد.
Run:  python3 -m pytest tests/test_r3_trends_context.py -q
"""
import os
import sys
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import block_network  # noqa: E402


def _market(name="Netherlands"):
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market(name)
    return ref


class _FakeTrendReq:
    """pytrends مموّه — يعيد DataFrames حقيقية (pandas مثبّت) لاختبار الاستخراج."""
    raise_on = ()  # أسماء قراءات تُثير استثناءً (لاختبار التدهور المستقل)

    def __init__(self, *a, **k):
        self.kw = None

    def build_payload(self, kw_list, timeframe=None, geo=None):
        self.kw = kw_list[0]

    def related_queries(self):
        if "related_queries" in self.raise_on:
            raise RuntimeError("boom")
        return {self.kw: {
            "top": pd.DataFrame({"query": ["تمر مجدول", "تمر عضوي"],
                                 "value": [100, 55]}),
            "rising": pd.DataFrame({"query": ["تمر رمضان"], "value": ["Breakout"]})}}

    def related_topics(self):
        if "related_topics" in self.raise_on:
            raise RuntimeError("boom")
        return {self.kw: {
            "rising": pd.DataFrame({"topic_title": ["رمضان"], "value": [90]}),
            "top": None}}

    def interest_by_region(self, resolution="REGION"):
        if "interest_by_region" in self.raise_on:
            raise RuntimeError("boom")
        return pd.DataFrame({self.kw: [80, 40]},
                            index=["Noord-Holland", "Zuid-Holland"])


# ── trends_context: العقد ─────────────────────────────────────────────────

def test_trends_context_offline_declares_gap_not_fabricate():
    import silk_trends_agent as T
    with block_network():
        out = T.trends_context("dates", geo="NL")
    assert out["related_top"] == [] and out["related_rising"] == []
    assert out["topics_rising"] == [] and out["regions"] == []
    assert out["confidence"] == 0.0
    assert out["note"]                       # سبب معلن


def test_trends_context_empty_keyword_declared():
    import silk_trends_agent as T
    out = T.trends_context("   ", geo="NL")
    assert out["confidence"] == 0.0 and out["related_top"] == []


def test_trends_context_extracts_all_sections():
    import silk_trends_agent as T
    with mock.patch("pytrends.request.TrendReq", _FakeTrendReq):
        out = T.trends_context("تمر", geo="NL")
    assert [r["label"] for r in out["related_top"]] == ["تمر مجدول", "تمر عضوي"]
    assert out["related_rising"][0]["label"] == "تمر رمضان"
    assert out["related_rising"][0]["value"] == "Breakout"     # نص لا رقم مختلَق
    assert out["topics_rising"][0]["label"] == "رمضان"
    assert [r["label"] for r in out["regions"]] == ["Noord-Holland", "Zuid-Holland"]
    assert out["confidence"] == 0.6


def test_trends_context_section_failure_is_independent():
    """قسم يفشل (related_topics) لا يُسقِط البقية — تدهور مستقل معلن."""
    import silk_trends_agent as T

    class _Partial(_FakeTrendReq):
        raise_on = ("related_topics",)

    with mock.patch("pytrends.request.TrendReq", _Partial):
        out = T.trends_context("تمر", geo="NL")
    assert out["related_top"]          # نجح
    assert out["regions"]              # نجح
    assert out["topics_rising"] == []  # فشل بصمت لا اختلاق


# ── أداة trends_context في runtime ────────────────────────────────────────

def test_trends_context_registered_as_tool():
    import silk_llm_runtime as RT
    assert "trends_context" in RT.TOOLS
    assert RT.TOOLS["trends_context"]["spec"]["name"] == "trends_context"


def test_tool_trends_context_returns_citable_datapoints():
    import silk_llm_runtime as RT
    canned = {"related_top": [{"label": "تمر مجدول", "value": 100}],
              "related_rising": [{"label": "تمر رمضان", "value": "Breakout"}],
              "topics_rising": [{"label": "رمضان", "value": 90}],
              "regions": [{"label": "Noord-Holland", "value": 80}],
              "confidence": 0.6, "note": "ok"}
    with mock.patch("silk_trends_agent.trends_context", return_value=canned):
        out = RT._tool_trends_context({"term": "تمر"}, {"market": _market(),
                                                        "product": "تمر"})
    assert len(out) == 4                     # نقطة لكل بند
    assert all(dp.value is not None for dp in out)
    kinds = {tuple(dp.value.keys())[0] for dp in out}
    assert {"related_query", "rising_query", "rising_topic", "region"} == kinds


def test_tool_trends_context_empty_is_declared_gap():
    import silk_llm_runtime as RT
    empty = {"related_top": [], "related_rising": [], "topics_rising": [],
             "regions": [], "confidence": 0.0, "note": "لا سياق"}
    with mock.patch("silk_trends_agent.trends_context", return_value=empty):
        out = RT._tool_trends_context({"term": "x"}, {"market": _market()})
    assert len(out) == 1 and out[0].value is None and out[0].confidence == 0.0


def test_tool_trends_context_uses_market_geo():
    import silk_llm_runtime as RT
    captured = {}

    def fake_ctx(term, geo=None, timeframe="today 12-m"):
        captured["geo"] = geo
        return {"related_top": [], "related_rising": [], "topics_rising": [],
                "regions": [], "confidence": 0.0, "note": "n"}

    with mock.patch("silk_trends_agent.trends_context", side_effect=fake_ctx):
        RT._tool_trends_context({"term": "تمر"}, {"market": _market("Netherlands")})
    assert captured["geo"] == "NL"           # iso2 السوق لا عالمياً


# ── توصيل البعثات + الزوايا الاستهلاكية ────────────────────────────────────

def test_consumer_culture_and_demand_trends_wire_trends_context():
    import silk_missions as M
    assert "trends_context" in M.MISSIONS["consumer_culture"]["allowed_tools"]
    assert "trends_context" in M.MISSIONS["demand_trends"]["allowed_tools"]


def test_consumer_culture_instructions_add_structured_angles():
    import silk_missions as M
    ins = M.MISSIONS["consumer_culture"]["instructions"]
    assert "trends_context" in ins
    assert "المناسبات والمواسم" in ins           # زاوية المناسبات
    assert "ثقافة الطعام" in ins                 # زاوية الثقافة المحلية
    assert "إعلام الجالية" in ins                # زاوية إعلام الجالية


def test_demand_trends_instructions_add_drivers():
    import silk_missions as M
    ins = M.MISSIONS["demand_trends"]["instructions"]
    assert "trends_context" in ins
    assert "محرّكات" in ins                      # محرّكات الطلب لا حجمه فقط

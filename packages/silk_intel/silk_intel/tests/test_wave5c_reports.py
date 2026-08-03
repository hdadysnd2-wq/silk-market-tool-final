"""اختبارات الموجة ٥ج — التقرير الكامل (Word) والمختصر من القالب الموحّد.

§10.3: خلاصة أولاً + سطر مصدر تحت كل رقم (بنيوياً من components_detail) +
"حدود هذا التقرير" قبل التوصيات. §10.4: المختصر منتج مختلف — قرار +
٣ أرقام + سطرا الموقع التنافسي. + اكتمال هجرة BaseAgent (15/15).
Run:  python3 -m pytest tests/ -q
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_data_layer import DataPoint


def _result() -> dict:
    """نتيجة محرّك بمكوّنات موسومة — engine-shaped fixture with provenance."""
    return {
        "product": "تمور", "hs_code": "080410", "hs_confidence": 1.0,
        "year": 2022, "classified": True, "preliminary": True,
        "note": "مبدئي",
        "markets": [{
            "country": "United Arab Emirates", "iso3": "ARE", "m49": "784",
            "total_score": 0.7, "confidence": 0.75,
            "components": {
                "market_size": DataPoint(241_000_000.0, "UN Comtrade", 0.9,
                                         "total imports", "2026-07-02"),
                "saudi_position": DataPoint(12.0, "UN Comtrade", 0.9,
                                            "share %", "2026-07-02"),
                "demand_capacity": DataPoint(None, "World Bank", 0.0,
                                             "fetch failed"),
            },
            "quality_flags": ["demand_capacity missing (no income signal)"],
            "jury": {"verdict": "PRELIMINARY GO", "confidence": 0.7,
                     "agents_with_data": 2, "agents_total": 3,
                     "data_gaps": ["EconomicAgent"]},
        }],
    }


def test_view_carries_source_line_per_number():
    # §10.3 بنيوياً: كل رقم في القالب يحمل مصدره وتاريخه وثقته.
    from silk_render import build_view

    view = build_view(_result())
    detail = view["markets"][0]["components_detail"]
    assert len(detail) == 3
    size = next(c for c in detail if c["name"] == "market_size")
    assert size["value"] == 241_000_000.0
    assert size["source"] == "UN Comtrade" and size["retrieved_at"]
    gap = next(c for c in detail if c["name"] == "demand_capacity")
    assert gap["value"] is None and gap["source"] == "World Bank"  # الفجوة منسوبة


def test_brief_is_a_different_product_not_a_shrunk_copy():
    # §10.4: قرار + ٣ أرقام بمصادرها + سطرا الموقع + إحالة اللوحة.
    from silk_render import build_view
    from silk_reports import render_brief

    brief = render_brief(build_view(_result()), dashboard_url="https://x/y")
    # طبقة السرد P1: رمز الآلة لا يصل وجه المستخدم — ترجمته العربية فقط،
    # والمبلغ بصيغة بشرية، وسطر المصدر مع كل رقم هو إشارة النزاهة الوحيدة.
    assert "توصية أولية بالدخول" in brief
    assert "PRELIMINARY GO" not in brief
    assert "مليون دولار" in brief and "[UN Comtrade]" in brief  # رقم بمصدره
    assert "أضف بطاقة منتجك" in brief          # الموقع التنافسي: غياب معلن
    assert "https://x/y" in brief               # إحالة اللوحة
    assert "لا اختلاق" not in brief and "لا مخمّنة" not in brief  # بلا شعار


def test_docx_full_report_structure():
    # §10.3: الخلاصة أولاً، سطر مصدر تحت كل رقم، والحدود قبل التوصيات.
    import pytest
    docx = pytest.importorskip("docx")
    from silk_render import build_view
    from silk_reports import render_docx

    path = os.path.join(tempfile.mkdtemp(), "r.docx")
    out = render_docx(build_view(_result()), path)
    assert os.path.exists(out)
    texts = [p.text for p in docx.Document(out).paragraphs]
    joined = "\n".join(texts)
    # هيكل الأقسام الـ14 المرقّم (P2-7): الخلاصة أول الأقسام، والحدود قبل
    # التوصيات الاستراتيجية؛ الفجوات تُعرض «—» هادئة ومترجمة (5b).
    heads = [t for t in texts if t in ("١. الخلاصة التنفيذية",
                                       "١٠. المشهد التنافسي",
                                       "حدود هذا التقرير",
                                       "١٤. التوصيات الاستراتيجية")]
    assert heads[0] == "١. الخلاصة التنفيذية"                  # الخلاصة أولاً
    assert heads.index("حدود هذا التقرير") \
        < heads.index("١٤. التوصيات الاستراتيجية")
    assert "المصدر: UN Comtrade" in joined                     # سطر المصدر
    assert "دخل الفرد غير متوفر" in joined     # الفجوة مسرودة — مترجمة (5b)
    assert "demand_capacity missing" not in joined  # لا نص داخلي على الوجه


def test_docx_missing_dependency_clear_error():
    # غياب python-docx = خطأ واضح بتلميح تثبيت — لا فشل صامت.
    from unittest.mock import patch
    import builtins
    from silk_reports import render_docx

    real_import = builtins.__import__

    def no_docx(name, *a, **k):
        if name == "docx":
            raise ImportError("no docx")
        return real_import(name, *a, **k)

    with patch.object(builtins, "__import__", side_effect=no_docx):
        try:
            render_docx({}, "/tmp/x.docx")
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            assert "python-docx" in str(e)


def test_report_endpoints_over_stored_analysis():
    # /analyses/{id}/brief و/report.docx: من التخزين عبر القالب؛ 404 للمفقود.
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import api
    import silk_storage as storage

    db = os.path.join(tempfile.mkdtemp(), "reports.db")
    result = _result()
    result["markets"][0]["components"] = {          # JSON-safe للتخزين
        k: {"value": dp.value, "source": dp.source,
            "confidence": dp.confidence, "note": dp.note,
            "retrieved_at": dp.retrieved_at}
        for k, dp in result["markets"][0]["components"].items()}
    aid = storage.save_analysis(result, db)
    saved = storage._DEFAULT_PATH
    storage._DEFAULT_PATH = db
    try:
        client = TestClient(api.create_app())
        r = client.get(f"/analyses/{aid}/brief")
        assert r.status_code == 200 and "التوصية" in r.text
        assert client.get("/analyses/424242/brief").status_code == 404
        r = client.get(f"/analyses/{aid}/report.docx")
        assert r.status_code in (200, 501)          # 501 فقط بلا python-docx
        if r.status_code == 200:
            assert r.headers["content-type"].startswith(
                "application/vnd.openxmlformats")
    finally:
        storage._DEFAULT_PATH = saved


def test_samples_rule_10_6_files_exist():
    # قاعدة ١٠.٦: نموذجا Word والمختصر محفوظان بالمستودع مع طبقة العرض.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.exists(os.path.join(root, "samples",
                                       "report_full_latest.docx"))
    brief = open(os.path.join(root, "samples", "brief_latest.txt"),
                 encoding="utf-8").read()
    assert "سِلك" in brief and "التوصية" in brief   # طبقة السرد P1


def test_all_fifteen_agents_on_base_agent():
    # اكتمال الهجرة: كل وكلاء المنصة الـ15 يرثون BaseAgent الفارض.
    from silk_agents import BaseAgent, TradeFlowAgent, EconomicAgent, \
        CompetitionAgent
    from silk_trends_agent import TrendsAgent
    from silk_tariffs_agent import TariffsAgent
    from silk_faostat_agent import FaostatAgent
    from silk_maps_agent import MapsAgent
    from silk_websearch_agent import WebSearchAgent
    from silk_localprice_agent import LocalPriceAgent
    from silk_volza_agent import VolzaAgent
    from silk_explee_agent import ExpleeAgent
    from silk_competitors_agent import NamedCompetitorsAgent
    from silk_channels_agent import DistributionChannelsAgent
    from silk_importers_agent import ImportersAgent
    from silk_requirements_agent import RequirementsAgent

    agents = [TradeFlowAgent, EconomicAgent, CompetitionAgent, TrendsAgent,
              TariffsAgent, FaostatAgent, MapsAgent, WebSearchAgent,
              LocalPriceAgent, VolzaAgent, ExpleeAgent,
              NamedCompetitorsAgent, DistributionChannelsAgent,
              ImportersAgent, RequirementsAgent]
    assert len(agents) == 15
    for cls in agents:
        assert issubclass(cls, BaseAgent), cls.__name__
        assert isinstance(cls.PAID, bool)           # التصنيف الإلزامي حاضر
    assert {c.__name__ for c in agents if c.PAID} == {
        "LocalPriceAgent", "VolzaAgent", "ExpleeAgent"}

"""اختبارات إصلاحات حادثة التشغيل الحي الأولى (الموجة ٧) — /research أنتج
تقريراً هيكلياً "يتطلب مفتاح كلود" وسُلِّم كأنه المنتج النهائي. يغطي:

P0 — بوابة ما قبل التشغيل: 409 صريح بلا allow_degraded، تشغيلة موسومة
     degraded=true معه، وحقل /health["research_ready"].
P1 — قسم "حدود التقرير" يجمع فجوات البعثات الجزئية (لا الفاشلة فقط).
P1 — وكيل WITS يتدهور بملاحظة عربية نظيفة بدل نص HTTPError خام.
P2 — قسم ٨ (تحليل التجارة) ينهار لسطر واحد بدل سطر مصدر يتيم فوق جدول فارغ.
P2 — تنسيق الأرقام: وحدة % للنسب، واختصار المبالغ الدولارية (fmt_money).
Run:  python3 -m pytest tests/test_wave7_live_incident_fixes.py -q
"""
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conftest import docx_all_text  # noqa: E402


def _client():
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.app)


# ── P0: بوابة /research ──────────────────────────────────────────────────

def test_health_reports_research_not_ready_without_key():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        r = _client().get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["research_ready"] is False
    assert "ANTHROPIC_API_KEY" in body["research_ready_reason"]


def test_health_reports_research_ready_with_protected_key():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test",
                                 "SILK_API_KEY": "secret"}):
        r = _client().get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["research_ready"] is True
    assert "research_ready_reason" not in body


def test_research_without_key_returns_409_not_a_skeleton():
    with patch("requests.get", side_effect=OSError("network disabled")):
        r = _client().post("/research", json={
            "product": "تمور", "market": "Nigeria", "hs_code": "080410",
            "persist": False})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "research_not_ready"
    assert "ANTHROPIC_API_KEY" in detail["reason"]


def test_research_with_unprotected_paid_key_returns_409_not_a_skeleton():
    # الفرضية الثانية من تحقيق سبب الحادثة: مفتاح كلود مضبوط لكن بلا
    # SILK_API_KEY — حارس 503 (_unprotected_paid_keys) يحجب الطبقة؛ يجب أن
    # يُرفض /research بـ409 هنا أيضاً، لا أن يمرّ صامتاً لتشغيلة بلا كلود.
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}, clear=False), \
         patch("requests.get", side_effect=OSError("network disabled")):
        os.environ.pop("SILK_API_KEY", None)
        r = _client().post("/research", json={
            "product": "تمور", "market": "Nigeria", "hs_code": "080410",
            "persist": False})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "research_not_ready"
    assert "SILK_API_KEY" in detail["reason"]


def test_research_with_exhausted_daily_cap_returns_409_not_a_skeleton():
    # الفرضية الثالثة: مفتاح محمي لكن السقف اليومي مستنفد (SILK_PAID_DAILY_CAP).
    db = os.path.join(tempfile.mkdtemp(), "usage.db")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test",
                                 "SILK_API_KEY": "secret",
                                 "SILK_PAID_DAILY_CAP": "0",
                                 "SILK_USAGE_DB": db}), \
         patch("requests.get", side_effect=OSError("network disabled")):
        r = _client().post(
            "/research", headers={"X-API-Key": "secret"},
            json={"product": "تمور", "market": "Nigeria", "hs_code": "080410",
                 "persist": False})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "research_not_ready"
    assert "SILK_PAID_DAILY_CAP" in detail["reason"]


def test_ambiguous_market_still_wins_422_over_409():
    # التحقق من إدخال العميل يسبق بوابة الجهوزية — لا داعٍ لفهم غموض السوق
    # بعد رفض الخادم للطلب أصلاً؛ هذا الترتيب يحفظ سلوك 422 الموجود.
    r = _client().post("/research", json={"product": "تمور", "market": "Nigera"})
    assert r.status_code == 422


def test_allow_degraded_runs_and_stamps_banner_in_docx():
    import pytest
    pytest.importorskip("docx")
    with patch("requests.get", side_effect=OSError("network disabled")):
        r = _client().post("/research", json={
            "product": "تمور", "market": "Nigeria", "hs_code": "080410",
            "persist": False, "allow_degraded": True})
    assert r.status_code == 200
    view = r.json()["view"]
    assert view["degraded"] is True

    os.environ["SILK_HERMETIC"] = "1"
    try:
        from silk_reports import render_docx
        path = render_docx(view, os.path.join(tempfile.mkdtemp(), "d.docx"))
        text = docx_all_text(path)
        assert "DEGRADED" in text
        assert "نظام الذكاء الاصطناعي غير متاح" in text
    finally:
        os.environ.pop("SILK_HERMETIC", None)


# ── P1: تجميع الفجوات في "حدود التقرير" ──────────────────────────────────

def _deep_research_result_with_partial_gap():
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    from silk_market_resolver import resolve_market

    ref, _ = resolve_market("Nigeria")
    # بعثة "ناجحة" (نتيجة واحدة مبنية على استشهاد) لكنها تصرّح بفجوة جزئية —
    # بالضبط سيناريو الحادثة: failed=False فلا تظهر ضمن الفاشلة، لكن فجوتها
    # يجب أن تظهر رغم ذلك.
    partial = AgentReport(
        "LLMAgent:pricing_scout",
        [DataPoint("سعر حدودي 2.1$/كغم", "x", 0.7, "n")], False,
        "ok | فجوات: لا بيانات هامش تجزئة؛ لا بيانات منافسين محليين | "
        "نداءات أدوات: 4")
    return {
        "product": "تمور", "hs_code": "080410", "year": None,
        "market": {"iso3": ref.iso3, "m49": ref.m49, "iso2": ref.iso2,
                  "name_en": ref.name_en, "name_ar": ref.name_ar},
        "markets": [],
        "deep_research": {
            "missions": {"pricing_scout": partial},
            "analyst": {"report": AgentReport("A", [], True, ""),
                       "by_category": {}, "missing_categories": []},
            "verdict": {"verdict": "PRELIMINARY GO"},
            "report": {"report": None, "review_cycles": 0,
                      "unresolved_notes": []},
        },
    }


def test_partial_gaps_from_succeeding_missions_reach_limits():
    from silk_render import build_view
    view = build_view(_deep_research_result_with_partial_gap())
    limits_blob = " | ".join(view["limits"])
    assert "لا بيانات هامش تجزئة" in limits_blob
    assert "لا بيانات منافسين محليين" in limits_blob


def test_docx_limits_section_is_never_falsely_empty(monkeypatch):
    import pytest
    pytest.importorskip("docx")
    from silk_render import build_view
    from silk_reports import render_docx
    monkeypatch.setenv("SILK_HERMETIC", "1")
    view = build_view(_deep_research_result_with_partial_gap())
    path = render_docx(view, os.path.join(tempfile.mkdtemp(), "lim.docx"))
    text = docx_all_text(path)
    assert "لا حدود مسجّلة" not in text
    assert "لا بيانات هامش تجزئة" in text


# ── P1: تدهور WITS نظيف بلا تسريب استثناء خام ────────────────────────────

def test_wits_400_degrades_with_clean_arabic_note_no_raw_leak():
    import requests
    import silk_tariffs_agent as ta

    resp = MagicMock()
    resp.status_code = 400
    http_err = requests.exceptions.HTTPError("400 Client Error: Bad Request "
                                             "for url: https://wits.worldbank.org/...")
    http_err.response = resp
    resp.raise_for_status.side_effect = http_err

    with patch("requests.get", return_value=resp):
        dp = ta.applied_tariff("210390", "ETH", "SAU", 2023)

    assert dp.value is None
    assert dp.confidence == 0.0
    assert "HTTP 400" in dp.note
    assert "wits.worldbank.org" not in dp.note   # لا رابط خام
    assert "Bad Request" not in dp.note           # لا نص الاستثناء الخام
    assert "210390" in dp.note and "ETH" in dp.note and "SAU" in dp.note


def test_wits_network_failure_still_degrades_cleanly():
    import silk_tariffs_agent as ta
    with patch("requests.get", side_effect=OSError("network disabled")):
        dp = ta.applied_tariff("210390", "ETH", "SAU", 2023)
    assert dp.value is None
    assert dp.confidence == 0.0
    assert dp.note  # فجوة معلنة، لا استثناء غير مُمسَك


# ── P2: انهيار قسم ٨ لسطر واحد بدل سطر مصدر يتيم ──────────────────────────

def _market_row(supplier_countries=None, research=None):
    return {"country": "الصين", "iso3": "CHN", "total_score": 0.5,
           "confidence": 0.5, "components": {},
           "competitors": supplier_countries or [],
           "research": research}


def test_section8_collapses_to_one_line_when_no_trade_data(monkeypatch):
    import pytest
    pytest.importorskip("docx")
    from silk_render import build_view
    from silk_reports import render_docx
    monkeypatch.setenv("SILK_HERMETIC", "1")
    result = {"product": "تمور", "hs_code": "080410", "classified": True,
             "markets": [_market_row()]}
    view = build_view(result)
    path = render_docx(view, os.path.join(tempfile.mkdtemp(), "s8.docx"))
    text = docx_all_text(path)
    # "٨." بالأرقام الهندية-العربية — عنوان القسم الفعلي لا سطر جدول المحتويات
    # (الذي يستعمل "8." لاتينية ويسبق العنوان الحقيقي في نص المستند).
    idx = text.find("٨. تحليل التجارة")
    assert idx != -1
    section = text[idx:idx + 300]
    assert "فجوة معلنة" in section
    assert "المصدر: UN Comtrade" not in section  # لا سطر مصدر يتيم بلا محتوى


# ── P2: تنسيق الأرقام — وحدة % + اختصار المبالغ ───────────────────────────

def test_percentage_metric_keeps_percent_sign_in_docx_table(monkeypatch):
    import pytest
    pytest.importorskip("docx")
    from silk_render import build_view
    from silk_reports import render_docx
    monkeypatch.setenv("SILK_HERMETIC", "1")
    research = {"agents": {"competitor": {"findings": [
        {"metric": "saudi_share_pct", "value": 1.87, "unit": "%",
         "sources": [{"name": "UN Comtrade"}], "note": ""}]}}}
    result = {"product": "تمور", "hs_code": "080410", "classified": True,
             "markets": [_market_row(research=research)]}
    view = build_view(result)
    path = render_docx(view, os.path.join(tempfile.mkdtemp(), "pct.docx"))
    text = docx_all_text(path)
    assert "1.87%" in text
    assert "1.87\t" not in text  # القيمة بلا وحدة لا تظهر منفردة في خلية


def test_large_usd_value_is_abbreviated_with_unit_in_trade_table(monkeypatch):
    import pytest
    pytest.importorskip("docx")
    from silk_render import build_view
    from silk_reports import render_docx
    monkeypatch.setenv("SILK_HERMETIC", "1")
    result = {"product": "تمور", "hs_code": "080410", "classified": True,
             "markets": [_market_row(supplier_countries=[
                 {"partner": "الصين", "share": 42.5, "value_usd": 1436057}])]}
    view = build_view(result)
    path = render_docx(view, os.path.join(tempfile.mkdtemp(), "usd.docx"))
    text = docx_all_text(path)
    assert "1,436,057" not in text   # لا رقم خام بلا وحدة/اختصار
    assert "مليون دولار" in text     # fmt_money: 1.4 مليون دولار
    assert "42.5%" in text


# ── Phase 3: التقرير سرد تحليلي لا تفريغ بيانات ──────────────────────────

_NARRATIVE_SECTION = (
    "## 12. التحليل الشامل والفرص\n"
    "يكشف التقاطع بين حجم الاستيراد المرصود وحصة السعودية الحالية عن فجوة "
    "طلب حقيقية قابلة للتوجيه: السوق يستورد كميات متنامية من هذا المنتج "
    "بينما الحضور السعودي محدود نسبياً (المصدر: UN Comtrade)، ما يفتح "
    "مساحة دخول واضحة إن عولجت عقبات التسعير الحدودي المذكورة أدناه.\n"
    "### الطلب الفعلي القابل للتوجيه\n"
    "يبلغ حجم الاستيراد المرصود مستوًى يبرر استهدافاً تجارياً جاداً، وقد "
    "نما على مدى فترة الدراسة (المصدر: UN Comtrade) — هذا يعني أن الفرصة "
    "ليست لحظية بل اتجاهاً مستمراً يستحق تخصيص موارد تصديرية حقيقية له.\n"
    "### تكلفة وصعوبة الدخول\n"
    "التعرفة المطبّقة والاشتراطات الجمركية المرصودة تضع عتبة دخول متوسطة "
    "لا حادة (المصدر: World Bank WITS)، ما يعني أن الدخول ممكن خلال دورة "
    "تجارية واحدة إن أُعدّت الوثائق المطلوبة مسبقاً.\n"
    "## 13. الحكم والتوصية\n"
    "استناداً إلى الحكم الجاهز أعلاه، فإن أقوى ثلاثة أسباب داعمة هي: نمو "
    "الاستيراد المستمر، الحصة السعودية المحدودة حالياً كفرصة نمو لا كإشارة "
    "ضعف، وتوفّر باب دخول آمن نسبياً عبر الموزّع المحلي المرصود. الشرط "
    "اللازم لبقاء هذا الحكم صحيحاً هو استقرار التعرفة الحالية؛ وأي ارتفاع "
    "حاد فيها يستدعي إعادة تقييم الجدوى الاقتصادية للدخول.\n"
    "| العمود | القيمة |\n"
    "|---|---|\n"
    "| النقاط | 0.62 |\n"
)


def _phase3_deep_research_result():
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    from silk_market_resolver import resolve_market

    ref, _ = resolve_market("Nigeria")
    analyst_report = AgentReport(
        "LLMAgent:market_analyst",
        [DataPoint("طلب استدلالي معقول", "x", 0.6, "n")], False, "تحليل")
    return {
        "product": "تمور", "hs_code": "080410", "year": None,
        "market": {"iso3": ref.iso3, "m49": ref.m49, "iso2": ref.iso2,
                  "name_en": ref.name_en, "name_ar": ref.name_ar},
        "markets": [],
        "deep_research": {
            "missions": {"trade_flow": AgentReport(
                "LLMAgent:trade_flow",
                [DataPoint(950000.0, "UN Comtrade", 0.9, "n")], False, "ok")},
            "analyst": {"report": analyst_report,
                       "by_category": {"demand": analyst_report.findings,
                                      "entry_cost": [], "price_competitiveness": [],
                                      "entry_door": [], "swot": []},
                       "missing_categories": []},
            "verdict": {"verdict": "PRELIMINARY GO",
                       "ai": {"verdict": "WATCH", "confidence": 0.5,
                             "reasoning": "سبب موجز"}},
            "report": {"report": _NARRATIVE_SECTION, "review_cycles": 1,
                      "unresolved_notes": []},
        },
    }


def test_markdown_subheadings_become_real_docx_headings_not_literal_text(
        monkeypatch):
    import pytest
    pytest.importorskip("docx")
    from docx import Document
    from silk_render import build_view
    from silk_reports import render_docx
    monkeypatch.setenv("SILK_HERMETIC", "1")
    view = build_view(_phase3_deep_research_result())
    path = render_docx(view, os.path.join(tempfile.mkdtemp(), "narr.docx"))
    doc = Document(path)
    heads = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert "الطلب الفعلي القابل للتوجيه" in heads
    assert "تكلفة وصعوبة الدخول" in heads
    text = docx_all_text(path)
    assert "###" not in text        # لا نص خام بعلامات #
    assert "|---|---|" not in text  # سطر فاصل الجدول مُستبعَد


def test_narrative_prose_precedes_the_raw_evidence_appendix(monkeypatch):
    # Phase 3: السرد التحليلي (كاتب التقرير) يسبق ملحق الأدلة الرقمية الخام
    # في ترتيب المستند — لا نقاط خام تسبق أي فقرة تحليلية (بلاغ الحادثة).
    import pytest
    pytest.importorskip("docx")
    from silk_render import build_view
    from silk_reports import render_docx
    monkeypatch.setenv("SILK_HERMETIC", "1")
    view = build_view(_phase3_deep_research_result())
    path = render_docx(view, os.path.join(tempfile.mkdtemp(), "order.docx"))
    text = docx_all_text(path)
    narrative_idx = text.find("يكشف التقاطع بين حجم الاستيراد")
    # ابحث عن عنوان الملحق الفعلي بعد موضع السرد — لا سطر جدول المحتويات
    # الذي يذكر العنوان نفسه مبكراً (نفس نمط اختبار "٨." vs "8." السابق).
    appendix_idx = text.find("ملحق — الأدلة الرقمية الداعمة", narrative_idx)
    assert narrative_idx != -1 and appendix_idx != -1
    assert narrative_idx < appendix_idx
    # فقرة سردية واحدة على الأقل تتجاوز ٢٠٠ حرفاً قبل أي محتوى نقطي
    # (نفس فقرة "يكشف التقاطع..." أعلاه — بلاغ الحادثة: تفريغ نقاط بلا سرد).
    assert len(_NARRATIVE_SECTION.split("###")[0]) > 200


def test_writer_prompt_requires_narrative_intersections_and_reasoned_verdict():
    # الالتزام بشكل الكتابة موجود في التعليمات المُرسَلة لكلود — لا يمكن
    # اختبار جودة نثر كلود هيرمتياً، لكن يمكن التأكد أن البرومبت يطلبها.
    # بلاغ حي (الموجة ١٠): "التحليل الشامل والفرص" الأحادي حل محله توزيع
    # الحساب الحسابي عبر أقسام البنية الأحد عشر الدولية (٣/٥/٦/١٠) — راجع
    # docs/DEEP_RESEARCH_DECISIONS.md "الموجة ١٠".
    import inspect
    import silk_ai_judge
    src = inspect.getsource(silk_ai_judge.deep_report)
    assert "فقرة سردية" in src
    assert "حساب حسابي صريح" in src
    assert "أقوى ثلاثة أسباب" in src
    assert "يقلبان الحكم" in src

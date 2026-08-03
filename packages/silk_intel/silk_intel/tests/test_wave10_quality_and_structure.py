"""اختبارات الموجة ١٠ (V5) — حلقة جودة ذاتية الإغلاق + بنية علمية دولية.

بلاغ المالك: خمس تشغيلات (ETH، NLD×٢، ESP) تثبت أن الأنابيب تعمل لكنها
تُسلِّم عيوباً صامتة يكتشفها المالك على الورق. يغطي: ١٠.١ (بوابة الجودة قبل
التسليم)، ١٠.٢أ (حلّ رموز شركاء كومتريد)، ١٠.٢ب (تصليب عائلة World Bank)،
١٠.٣ (البنية العلمية الدولية بأحد عشر قسماً)، ١٠.٤ (وضوح الكاتب + تنبيه
بطاقة المنتج).
Run:  python3 -m pytest tests/test_wave10_quality_and_structure.py -q
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── ١٠.٢أ: حلّ رموز شركاء كومتريد — countries.csv (٢٥٠) + خاصون + معلَن ──

def test_partner_name_resolves_beyond_the_old_seventy_country_list():
    from silk_data_layer import partner_name
    # إسبانيا (بلاغ حي، الموجة ١٠/١١) وأخرى خارج القائمة القديمة الصغيرة.
    assert partner_name("724") == "Spain"
    assert partner_name(724) == "Spain"
    assert partner_name("156") == "China"


def test_partner_name_resolves_countries_outside_old_seed_list():
    from silk_data_layer import partner_name
    # بلاغ حي: القائمة القديمة (٧٠ دولة) لم تكن تغطي معظم إفريقيا/أمريكا
    # اللاتينية — countries.csv (٢٥٠ دولة) يحلّها الآن.
    assert partner_name("270") == "Gambia"
    assert partner_name("858") == "Uruguay"


def test_partner_name_handles_comtrade_special_and_world_codes():
    from silk_data_layer import partner_name
    assert partner_name("0") == "World"
    assert partner_name("899") == "Areas, nes"


def test_partner_name_never_returns_a_bare_digit_string():
    from silk_data_layer import partner_name
    # رمز غير معروف كلياً — لا يُعاد رقماً خاماً، بل تسمية معلنة صراحة.
    name = partner_name("777777")
    assert not name.isdigit()
    assert "777777" in name  # الرقم مذكور للتتبع، لكن ضمن تسمية لا بمفرده


def test_comtrade_competitors_tool_returns_real_names_and_hhi(monkeypatch):
    import silk_llm_runtime as rt
    from silk_data_layer import DataPoint
    from silk_market_resolver import resolve_market

    def fake_market_competitors(hs, m49, year):
        return [
            DataPoint({"partner": "France", "code": "250", "value_usd": 700.0,
                      "share": 70.0}, "UN Comtrade", 0.9, "n"),
            DataPoint({"partner": "Morocco", "code": "504", "value_usd": 300.0,
                      "share": 30.0}, "UN Comtrade", 0.9, "n"),
        ]

    monkeypatch.setattr("silk_data_layer_v2.market_competitors",
                        fake_market_competitors)
    ref, _ = resolve_market("Spain")
    out = rt._tool_comtrade_competitors(
        {"year": 2023}, {"hs_code": "080410", "market": ref})
    assert out[0].value["hhi"] == 70.0 ** 2 + 30.0 ** 2
    names = [d.value["partner"] for d in out[1:]]
    assert names == ["France", "Morocco"]
    assert all(not str(n).isdigit() for n in names)


def test_comtrade_competitors_no_data_declares_gap_not_empty_silence():
    # ترقية المرحلة ٢ج (خيار A — إحصاءات المرآة): الاستعلام المباشر فارغ
    # لا يكفي وحده لإعلان الفجوة بعد الآن — _tool_comtrade_competitors
    # يحاول احتياط المرآة أولاً (market_competitors_mirror)، فيجب تعطيله
    # هو أيضاً هنا كي يبقى هذا اختبار "لا بيانات في أي مصدر" لا اختبار
    # الاحتياط الجديد (له اختبارات مخصَّصة في
    # test_phase2c_a_mirror_statistics.py).
    import silk_llm_runtime as rt
    from silk_market_resolver import resolve_market

    ref, _ = resolve_market("Spain")

    def fake_no_data(hs, m49, year):
        return []

    import silk_data_layer_v2
    orig = silk_data_layer_v2.market_competitors
    orig_mirror = silk_data_layer_v2.market_competitors_mirror
    silk_data_layer_v2.market_competitors = fake_no_data
    silk_data_layer_v2.market_competitors_mirror = fake_no_data
    try:
        out = rt._tool_comtrade_competitors(
            {"year": 2023}, {"hs_code": "080410", "market": ref})
    finally:
        silk_data_layer_v2.market_competitors = orig
        silk_data_layer_v2.market_competitors_mirror = orig_mirror
    assert len(out) == 1
    assert out[0].value is None
    assert out[0].confidence == 0.0


def test_competitors_mission_calls_comtrade_competitors_before_web_search():
    from silk_missions import MISSIONS
    m = MISSIONS["competitors"]
    assert "comtrade_competitors" in m["allowed_tools"]
    assert m["allowed_tools"].index("comtrade_competitors") < \
        m["allowed_tools"].index("web_search")
    assert "أولاً" in m["instructions"]


# ── ١٠.٢ب: تصليب عائلة World Bank — تحقّق شكل + مصفوفة تثبيت ─────────────
#
# مصفوفة {NLD, ESP, ETH, CHN, EGY} × {population, income, WGI political-
# stability, WGI regulatory-quality, FX}. القيم أدناه تمثيلية (بنية ردّ
# البنك الدولي الموثَّقة حرفياً — envelope [{page,...}, [records]] — لا
# أرقام مسحوبة حياً؛ لا شبكة في هذه البيئة، والاختبار يتحقق من التفسير
# البنيوي الصحيح، لا من دقة الرقم بذاته). هذا هو حارس الانحدار الدائم
# بدل الترقيع قطراً بقطر (بلاغ حي: WGI فارغ لهولندا ثم إسبانيا تباعاً).

_WB_FIXTURE_MATRIX = {
    ("NLD", "SP.POP.TOTL"): (17_900_000.0, "2022"),
    ("NLD", "NY.GDP.PCAP.CD"): (55_980.0, "2022"),
    ("NLD", "PV.EST"): (1.18, "2022"),
    ("NLD", "RQ.EST"): (1.72, "2022"),
    ("NLD", "PA.NUS.FCRF"): (0.95, "2022"),
    ("ESP", "SP.POP.TOTL"): (47_500_000.0, "2022"),
    ("ESP", "NY.GDP.PCAP.CD"): (29_350.0, "2022"),
    ("ESP", "PV.EST"): (0.58, "2022"),
    ("ESP", "RQ.EST"): (1.02, "2022"),
    ("ESP", "PA.NUS.FCRF"): (0.95, "2022"),
    ("ETH", "SP.POP.TOTL"): (120_300_000.0, "2022"),
    ("ETH", "NY.GDP.PCAP.CD"): (1_020.0, "2022"),
    ("ETH", "PV.EST"): (-1.49, "2022"),
    ("ETH", "RQ.EST"): (-0.88, "2022"),
    ("ETH", "PA.NUS.FCRF"): (53.7, "2022"),
    ("CHN", "SP.POP.TOTL"): (1_412_000_000.0, "2022"),
    ("CHN", "NY.GDP.PCAP.CD"): (12_720.0, "2022"),
    ("CHN", "PV.EST"): (-0.29, "2022"),
    ("CHN", "RQ.EST"): (-0.24, "2022"),
    ("CHN", "PA.NUS.FCRF"): (6.73, "2022"),
    ("EGY", "SP.POP.TOTL"): (104_000_000.0, "2022"),
    ("EGY", "NY.GDP.PCAP.CD"): (3_900.0, "2022"),
    ("EGY", "PV.EST"): (-0.62, "2022"),
    ("EGY", "RQ.EST"): (-0.47, "2022"),
    ("EGY", "PA.NUS.FCRF"): (19.2, "2022"),
}


def _wb_envelope(value, date):
    """جسم ردّ البنك الدولي الحقيقي — [{page,...}, [{...,"value":v,"date":d}]]."""
    return [{"page": 1, "pages": 1, "per_page": "100", "total": 1},
           [{"indicator": {"id": "X"}, "country": {"id": "XX"}, "date": date,
             "value": value, "unit": "", "obs_status": "", "decimal": 0}]]


def test_world_bank_fixture_matrix_five_countries_five_indicators():
    import silk_data_layer as DL
    for (iso3, code), (value, date) in _WB_FIXTURE_MATRIX.items():
        payload = _wb_envelope(value, date)
        with mock.patch.object(DL, "_cached_get", return_value=payload):
            dp = DL.world_bank(iso3, code)
        assert dp.value == value, f"{iso3}/{code}"
        assert dp.source == "World Bank"
        assert dp.confidence > 0


def test_world_bank_shape_error_envelope_produces_clear_diagnostic_note():
    import silk_data_layer as DL
    # شكل خطأ API حقيقي: [{"message":[{"id":"120","key":"Invalid value"}]}]
    error_payload = [{"message": [{"id": "120", "key": "Invalid value",
                                   "value": "Invalid indicator value"}]}]
    with mock.patch.object(DL, "_cached_get", return_value=error_payload):
        dp = DL.world_bank("NLD", "BAD.CODE")
    assert dp.value is None
    assert "خطأ API" in dp.note or "Invalid" in dp.note


def test_world_bank_shape_error_null_records_page_no_crash():
    import silk_data_layer as DL
    # صفحة صالحة بلا سجلات (مؤشر/دولة بلا بيانات إطلاقاً) — ليس خطأ شكل،
    # فجوة حقيقية معلنة، لا استثناء.
    with mock.patch.object(DL, "_cached_get",
                           return_value=[{"page": 1}, None]):
        dp = DL.world_bank("NLD", "SOME.CODE")
    assert dp.value is None
    assert dp.confidence == 0.0


def test_world_bank_shape_error_malformed_records_type_no_crash():
    import silk_data_layer as DL
    with mock.patch.object(DL, "_cached_get",
                           return_value=[{"page": 1}, "not-a-list"]):
        dp = DL.world_bank("ESP", "SOME.CODE")
    assert dp.value is None
    assert "ليست قائمة" in dp.note


def test_exchange_rate_indicator_registered_and_callable_by_missions():
    import silk_llm_runtime as rt
    assert rt._WB_INDICATORS["exchange_rate"] == "PA.NUS.FCRF"
    assert rt._WB_INDICATORS["regulatory_quality"] == "RQ.EST"


def test_risk_news_instructs_multi_year_fx_calls_for_volatility():
    from silk_missions import MISSIONS
    instr = MISSIONS["risk_news"]["instructions"]
    assert "exchange_rate" in instr
    assert "خمسة عناوين" in instr


# ── ١٠.٣: البنية العلمية الدولية بأحد عشر قسماً (Euromonitor/ESOMAR) ──────

_EXPECTED_SECTIONS = (
    "الخلاصة التنفيذية", "منهجية البحث ونطاقه", "نظرة عامة على السوق وحجمه",
    "ديناميكيات السوق", "تحليل المستهلك والطلب", "المشهد التنافسي",
    "التنظيم والوصول للسوق", "اللوجستيات وسلسلة الإمداد", "تقييم المخاطر",
    "التوصيات الاستراتيجية", "الملاحق",
)


def test_report_sections_is_the_exact_eleven_section_canonical_order():
    import silk_ai_judge
    assert silk_ai_judge._REPORT_SECTIONS == _EXPECTED_SECTIONS


def _draft_from_sections(sections):
    return "\n".join(f"## {i}. {s}\nنص." for i, s in enumerate(sections, 1))


def test_section_order_issues_clean_on_a_complete_ordered_draft():
    import silk_ai_judge
    draft = _draft_from_sections(silk_ai_judge._REPORT_SECTIONS)
    assert silk_ai_judge._section_order_issues(draft) == []


def test_section_order_issues_flags_missing_section():
    import silk_ai_judge
    partial = [s for s in silk_ai_judge._REPORT_SECTIONS if s != "تقييم المخاطر"]
    draft = _draft_from_sections(partial)
    issues = silk_ai_judge._section_order_issues(draft)
    assert any("تقييم المخاطر" in i for i in issues)


def test_section_order_issues_flags_wrong_order():
    import silk_ai_judge
    shuffled = list(silk_ai_judge._REPORT_SECTIONS)
    shuffled[0], shuffled[1] = shuffled[1], shuffled[0]
    draft = _draft_from_sections(shuffled)
    issues = silk_ai_judge._section_order_issues(draft)
    assert any("ترتيب" in i for i in issues)


def test_review_report_rejects_incomplete_draft_even_without_llm_reply(
        monkeypatch):
    import silk_ai_judge
    monkeypatch.setattr(silk_ai_judge, "available", lambda: True)
    monkeypatch.setattr(silk_ai_judge, "_call", lambda *a, **k: None)
    incomplete = "## 1. الخلاصة التنفيذية\nنص فقط."
    result = silk_ai_judge.review_report(incomplete, {})
    assert result is not None
    assert result["approved"] is False
    assert result["issues"]


def test_review_report_llm_issues_combined_with_structural_issues(
        monkeypatch):
    import silk_ai_judge
    monkeypatch.setattr(silk_ai_judge, "available", lambda: True)
    raw = '{"issues": ["رقم غير مسنود"], "approved": false}'
    monkeypatch.setattr(silk_ai_judge, "_call", lambda *a, **k: raw)
    incomplete = "## 1. الخلاصة التنفيذية\nنص فقط."
    result = silk_ai_judge.review_report(incomplete, {})
    assert "رقم غير مسنود" in result["issues"]
    assert any("أقسام مفقودة" in i for i in result["issues"])
    assert result["approved"] is False


def test_mission_to_section_covers_all_twelve_missions():
    import silk_ai_judge
    from silk_missions import MISSIONS
    for key in MISSIONS:
        assert key in silk_ai_judge._MISSION_TO_SECTION
        assert silk_ai_judge._MISSION_TO_SECTION[key] in _EXPECTED_SECTIONS


# ── ١٠.١: بوابة الجودة قبل التسليم — ثوابت عيوب التشغيلات #٣/#٥(ESP) ─────

def _defective_view():
    """يحاكي بالضبط أعراض تشغيلتَي #٣ وESP (#٥) المُبلَّغتين: رمز شريك خام
    (899 بدل اسم)، "دليل غير كافٍ" رغم ٣ بنود طلب، بعثة بلا نتائج، تسريب
    Markdown/JSON/ثقة خام، تقطيع منتصف كلمة، وبنية أقسام ناقصة/مبعثرة."""
    demand_items = [
        {"value": "بند طلب ١", "source": "x", "confidence": 0.6, "note": "n"},
        {"value": "بند طلب ٢", "source": "x", "confidence": 0.6, "note": "n"},
        {"value": "بند طلب ٣", "source": "x", "confidence": 0.6, "note": "n"},
    ]
    report_text = (
        "## 1. الخلاصة التنفيذية\n"
        "**نص عريض** بصيغة ماركداون متسرّبة ```كود``` (ثقة 0.9).\n"
        "## 3. نظرة عامة على السوق وحجمه\n"
        "الطلب الفعلي القابل للتوجيه: دليل غير كافٍ رغم البيانات المرفقة"
        " اعلن الفجوة هنا بلا حساب رغم توفر ثلاثة بنود مرتبطة فعلياً بلا شك"
        " {\"raw\": \"json leaking\"}\n"
        "هذا سطر ينتهي منتصف كلمة بلا أي علامة ترقيم ختامية يستمر طويلاً جد\n"
    )
    return {"deep_research": {
        "missions": {
            "competitors": {"failed": False, "summary": "ok", "findings": [
                {"value": {"partner": "899", "code": "899",
                          "value_usd": 100.0, "share": 10.0},
                 "source": "UN Comtrade", "confidence": 0.9, "note": "n",
                 "retrieved_at": "2026-01-01", "status": ""}]},
            "risk_news": {"failed": True, "summary": "فشل الاتصال",
                         "findings": []},
        },
        "analyst": {"by_category": {
            "demand": demand_items, "entry_cost": [], "price_competitiveness": [],
            "entry_door": [], "swot": []}},
        "report": {"text": report_text, "review_cycles": 1,
                  "unresolved_notes": []},
    }}


def test_quality_gate_flags_bare_partner_code():
    import silk_quality_gate as qg
    out = qg.run_quality_gate(_defective_view())
    checks = {f["check"] for f in out["findings"]}
    assert "bare_partner_code" in checks


def test_quality_gate_flags_insufficiency_despite_evidence():
    import silk_quality_gate as qg
    out = qg.run_quality_gate(_defective_view())
    checks = {f["check"] for f in out["findings"]}
    assert "intersection_insufficiency" in checks


def test_quality_gate_flags_agent_health_zero_findings_mission():
    """بلاغ منتج من المالك: الملاحظة تحمل اسم البعثة التجاري بالعربية
    (تقييم المخاطر والمستجدات) لا المفتاح snake_case الخام (risk_news) —
    سباكة داخلية لا يجوز أن تصل نصاً معروضاً للعميل."""
    import silk_quality_gate as qg
    out = qg.run_quality_gate(_defective_view())
    notes = " ".join(f["note"] for f in out["findings"])
    assert "risk_news" not in notes
    assert "تقييم المخاطر والمستجدات" in notes


def test_quality_gate_flags_markdown_and_raw_json_and_raw_confidence():
    import silk_quality_gate as qg
    out = qg.run_quality_gate(_defective_view())
    checks = {f["check"] for f in out["findings"]}
    assert "markdown_artifacts" in checks
    assert "raw_json" in checks
    assert "raw_confidence" in checks


def test_quality_gate_flags_mid_word_truncation():
    import silk_quality_gate as qg
    out = qg.run_quality_gate(_defective_view())
    checks = {f["check"] for f in out["findings"]}
    assert "mid_word_truncation" in checks


def test_quality_gate_flags_incomplete_section_structure():
    import silk_quality_gate as qg
    out = qg.run_quality_gate(_defective_view())
    checks = {f["check"] for f in out["findings"]}
    assert "section_structure" in checks


def test_quality_gate_verdict_is_fail_for_the_known_defect_fixture():
    import silk_quality_gate as qg
    out = qg.run_quality_gate(_defective_view())
    assert out["verdict"] == qg.FAIL


def test_quality_gate_pass_on_a_clean_view():
    import silk_quality_gate as qg
    clean = {"deep_research": {
        "missions": {"trade_flow": {"failed": False, "summary": "ok",
                                    "findings": [{"value": 100.0,
                                                 "source": "x",
                                                 "confidence": 0.9,
                                                 "note": "n"}]}},
        "analyst": {"by_category": {}},
        "report": {"text": "", "review_cycles": 0, "unresolved_notes": []},
    }}
    out = qg.run_quality_gate(clean)
    assert out["verdict"] == qg.PASS
    assert out["findings"] == []


def test_quality_gate_no_op_on_classic_analyze_view_without_deep_research():
    import silk_quality_gate as qg
    out = qg.run_quality_gate({"markets": []})
    assert out["verdict"] == qg.PASS
    assert out["findings"] == []


def test_quality_gate_repairable_findings_do_not_leak_into_methodology_notes():
    import silk_quality_gate as qg
    out = qg.run_quality_gate(_defective_view())
    notes_text = " ".join(out["methodology_notes"])
    # القابلة للإصلاح (markdown/ثقة خام/تقطيع) لا تظهر كملاحظة منهجية —
    # طبقة العرض تُصلحها فعلاً؛ فقط البنيوية غير القابلة للإصلاح تظهر.
    assert "899" in notes_text or "شريك" in notes_text
    assert "risk_news" not in notes_text
    assert "تقييم المخاطر والمستجدات" in notes_text


def test_research_endpoint_attaches_quality_gate_to_view(monkeypatch):
    import json
    import os
    import tempfile
    from unittest.mock import patch

    def fake_call_tools(system, messages, tools=None, max_tokens=1600,
                        model=None, timeout=None):
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(
                {"findings": [], "gaps": [], "summary": "ok"})}]}

    def fake_call(system, user, max_tokens=1600, model=None, timeout=None):
        return json.dumps({"verdict": "WATCH", "confidence": 0.5,
                           "reasoning": "ok"})

    db = os.path.join(tempfile.mkdtemp(), "silk.db")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test",
                                 "SILK_API_KEY": "secret"}), \
         patch("silk_llm_runtime._call_tools", side_effect=fake_call_tools), \
         patch("silk_synthesis._call", side_effect=fake_call), \
         patch("silk_ai_judge._call", side_effect=fake_call), \
         patch("silk_storage._db_path", return_value=db):
        from fastapi.testclient import TestClient
        import api
        r = TestClient(api.app).post(
            "/research", headers={"X-API-Key": "secret"},
            json={"product": "تمور", "market": "Nigeria", "hs_code": "080410",
                 "persist": False})
    assert r.status_code == 200
    gate = r.json()["view"]["deep_research"]["quality_gate"]
    assert gate["verdict"] in ("PASS", "PASS-WITH-WARNINGS", "FAIL")
    assert "findings" in gate


# ── ١٠.٤: وضوح الكاتب + تنبيه بطاقة المنتج (لا حجب) ──────────────────────

def test_writer_prompt_phrases_missing_product_card_correctly_not_contradictory():
    import silk_ai_judge
    import inspect
    src = inspect.getsource(silk_ai_judge.deep_report)
    assert "أسعار السوق مرصودة؛ موقعك السعري يتطلب بطاقة منتجك" in src


def test_dashboard_shows_product_card_nudge_without_blocking_request():
    html = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "web", "index.html"), encoding="utf-8").read()
    assert "بدون بطاقة المنتج سيغيب عمود الربحية" in html
    # التنبيه في فرع else من فحص بطاقة المنتج — لا يمنع إرسال الطلب (بعده
    # مباشرة يُكمَل بناء الجسم b وإرساله عبر post("/research", b) بلا شرط).
    idx = html.find("بدون بطاقة المنتج سيغيب عمود الربحية")
    tail = html[idx:idx + 400]
    assert 'post("/research"' in tail


def test_javascript_syntax_valid_after_nudge_edit():
    import shutil
    node = shutil.which("node")
    if not node:
        return
    import re
    import subprocess
    import tempfile
    html = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "web", "index.html"), encoding="utf-8").read()
    m = re.search(r"<script>(.*)</script>", html, re.S)
    assert m
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(m.group(1))
        tmp_path = f.name
    try:
        r = subprocess.run([node, "--check", tmp_path], capture_output=True)
        assert r.returncode == 0, r.stderr.decode()
    finally:
        os.unlink(tmp_path)


def test_methodology_section_renders_gate_notes_not_cover_alarm(monkeypatch):
    import os
    import tempfile
    from silk_render import build_view
    from silk_reports import render_docx
    import silk_quality_gate as qg
    from conftest import docx_all_text

    monkeypatch.setenv("SILK_HERMETIC", "1")
    result = {
        "product": "تمور", "hs_code": "080410", "year": None,
        "market": {"iso3": "NGA", "m49": "566", "iso2": "NG",
                  "name_en": "Nigeria", "name_ar": "نيجيريا"},
        "markets": [],
        "deep_research": {
            "missions": {"trade_flow": {"name": "x", "failed": False,
                                        "summary": "ok", "findings": []}},
            "analyst": {"summary": "s", "missing_categories": [],
                       "by_category": {}},
            "verdict": {"verdict": "WATCH"},
            "report": {"report": "## 2. منهجية البحث ونطاقه\nنص منهجي."},
        },
    }
    view = build_view(result)
    gate_out = qg.run_quality_gate(view)
    gate_out["methodology_notes"] = ["ملاحظة منهجية اختبارية فريدة"]
    view["deep_research"]["quality_gate"] = gate_out
    path = os.path.join(tempfile.mkdtemp(), "gate.docx")
    render_docx(view, path)
    text = docx_all_text(path)
    assert "ملاحظة منهجية اختبارية فريدة" in text
    assert "حدود المنهجية وجودة البيانات" in text

"""اختبارات «التقرير التنفيذي متعدد الأسواق» — القسم التنفيذي في النموذج
القانوني + مشتقّ Word التنفيذي (render_executive_docx).

الثوابت المُختبَرة:
1. القسم يلتصق بالنموذج فقط حين يغذّي جانبُ المنتج `result["executive"]` —
   غيابه = لا مفتاح "executive" إطلاقاً (سلوك /analyze القائم بلا تغيير).
2. الملاحظات الحرة تمرّ عبر مُطهِّر السباكة الداخلية (لا LLMAgent/dp7 على
   وجه العميل)، والقوائم الفارغة تبقى [] (تُعلَن «غير مرصود» — لا صفوف مخترعة).
3. المشتقّ يُصيَّر docx فعلياً (PK zip) ببيانات كاملة، ويعلن فجواته ببياناتٍ
   ناقصة بسلاسل العقد الحرفية («سعر غير مرصود» / «لا مشترون مرصودون بعد
   لهذا السوق»)، ولا ينهار على نموذج فجوة كلية (بلا أسواق).
4. حكم واحد لا حكمان: حكم view["decision"] وحده في المشتقّ — لا رمز آلة خام
   ولا ترجمة حكم الجورية المخالف.
5. حارس الإنتاج ساري: أثر برهاني (MagicMock) خارج SILK_HERMETIC = رفض التوليد.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _executive_payload() -> dict:
    """حمولة عقد جانب المنتج — نفس شكل result["executive"] المتفق عليه."""
    _at = "2026-08-01"

    def _rc(value, source, note=""):
        return {"value": value, "source": source, "confidence": 0.85,
                "note": note, "retrieved_at": _at}

    return {
        "screening": {"total_screened": 38, "analysis_status": "complete",
                      "analysis_at": f"{_at}T00:00:00Z"},
        "markets": [
            {"country": "الصين", "iso3": "CHN", "iso2": "CN",
             "score": 0.62, "score_confidence": 0.72,
             "rationale_components": {
                 "market_size": _rc(6.0e7, "UN Comtrade", "واردات 2023"),
                 "saudi_position": _rc(30.0, "UN Comtrade"),
                 "demand_capacity": _rc(None, "World Bank", "تعذّر الجلب"),
                 "competition": _rc(
                     0.25, "UN Comtrade",
                     "LLMAgent:trade_flow قاسها من dp7 [dp3]"),
             },
             "tags": ["سوق كبير"], "transit_hub": False,
             "prices": [
                 {"competitor": "علامة منافسة أ", "price": 12.5,
                  "currency": "USD", "store": "متجر إلكتروني",
                  "url": "https://shop.sample/a", "source": "رصد ويب",
                  "confidence": 0.6, "retrieved_at": _at}],
             "competitors": [
                 {"exporter_name": "إيران", "share_pct": 50.0,
                  "value_usd": 3.0e7, "source": "UN Comtrade",
                  "confidence": 0.9, "retrieved_at": _at}],
             "buyers": [
                 {"name": "مستورد أغذية — شنغهاي", "source": "خرائط الويب",
                  "confidence": 0.5, "relevance_score": 0.8, "contacts": 2,
                  "legal_review_required": True}]},
            # سوق ناقص عمداً: بلا أسعار وبلا مشترين (+ محور عبور) — تُعلَن
            # فجواته بسطريها الحرفيين في المشتقّ، ولا تُخترع صفوف.
            {"country": "الإمارات", "iso3": "ARE", "iso2": "AE",
             "score": 0.55, "score_confidence": 0.66,
             "rationale_components": {
                 "market_size": _rc(2.0e7, "UN Comtrade"),
                 "saudi_position": _rc(70.0, "UN Comtrade"),
                 "demand_capacity": _rc(None, "World Bank", "تعذّر الجلب"),
                 "competition": _rc(0.49, "UN Comtrade"),
             },
             "tags": [], "transit_hub": True,
             "prices": [], "competitors": [
                 {"exporter_name": "السعودية", "share_pct": 70.0,
                  "value_usd": 1.4e7, "source": "UN Comtrade",
                  "confidence": 0.9, "retrieved_at": _at}],
             "buyers": []},
        ],
    }


def _result(executive: "dict | None" = None, with_market: bool = True) -> dict:
    """نتيجة محرّك دنيا حتمية — سوق أعلى بحكم §8 صالح (يخالف حكم الجورية
    عمداً — ثابت الحكم الواحد) أو بلا أسواق إطلاقاً."""
    res = {"product": "تمور", "hs_code": "080410", "hs_confidence": 0.9,
           "year": 2023, "classified": True, "markets": []}
    if with_market:
        res["markets"] = [{
            "country": "الصين", "iso3": "CHN", "total_score": 0.62,
            "confidence": 0.7, "components": {}, "quality_flags": [],
            "jury": {"verdict": "NO-GO", "agents_with_data": 2,
                     "agents_total": 3, "data_gaps": [],
                     "synthesis_stage": "stage1"},
            "decision": {"schema": "silk.decision/v1",
                         "verdict": "CONDITIONAL-GO", "confidence": 0.64,
                         "score": 61.0, "why": "سوق واعد بشروط معلنة"},
        }]
    if executive is not None:
        res["executive"] = executive
    return res


def _docx_path() -> str:
    return os.path.join(tempfile.mkdtemp(), "executive.docx")


# ── 1+2) القسم التنفيذي في النموذج القانوني ──────────────────────────────────

def test_executive_absent_keeps_view_unchanged():
    """بلا result["executive"] لا يظهر مفتاح "executive" في النموذج إطلاقاً —
    سلوك /analyze القائم كما هو (غياب لا فراغ)."""
    from silk_render import build_view
    view = build_view(_result())
    assert "executive" not in view
    # وحكم النموذج الواحد قائم كما كان (حارس Stage 5 يرث هذا بنيوياً).
    assert view["decision"]["verdict"] == "CONDITIONAL-GO"


def test_executive_section_attaches_normalizes_and_declares():
    """القسم يلتصق حين يُغذَّى: الفرز كما ورد، الملاحظات مُطهَّرة من السباكة
    الداخلية، القوائم الفارغة تبقى []، وجهات الاتصال عددٌ صحيح."""
    from silk_render import build_view
    view = build_view(_result(executive=_executive_payload()))
    ex = view["executive"]
    # الفرز يُحمَل كما ورد.
    assert ex["screening"] == {"total_screened": 38,
                               "analysis_status": "complete",
                               "analysis_at": "2026-08-01T00:00:00Z"}
    assert [m["iso3"] for m in ex["markets"]] == ["CHN", "ARE"]
    chn = ex["markets"][0]
    # التطبيع: القيمة/المصدر/الثقة/التاريخ تسافر معاً في كل مكوّن مبرّر.
    comp = chn["rationale_components"]["competition"]
    assert comp["value"] == 0.25 and comp["source"] == "UN Comtrade"
    assert comp["retrieved_at"] == "2026-08-01"
    # مُطهِّر السباكة: لا LLMAgent:<key> ولا وسم dp خام على وجه العميل.
    assert "LLMAgent" not in comp["note"] and "dp7" not in comp["note"]
    assert "dp3" not in comp["note"]
    # فجوة معلنة تبقى None — لا تصفير مختلَق.
    assert chn["rationale_components"]["demand_capacity"]["value"] is None
    assert chn["components_present"] == "3/4"
    # جهات الاتصال عدد صحيح، وعلم المراجعة القانونية منطقي.
    buyer = chn["buyers"][0]
    assert buyer["contacts"] == 2 and buyer["legal_review_required"] is True
    # القوائم الفارغة/الغائبة تبقى [] — المستهلك يعلن «غير مرصود».
    are = ex["markets"][1]
    assert are["prices"] == [] and are["buyers"] == []
    assert are["transit_hub"] is True
    # الوصف الرسمي للرمز من المرجع المحلي (موجود لرمز التمور 080410).
    assert isinstance(ex["hs_official_description"], str)


def test_executive_section_tolerates_missing_lists_and_bad_rows():
    """صفوف مشوَّهة تُسقَط (لا تُصفَّر)، ومفاتيح قوائم غائبة كلياً = []."""
    from silk_render import build_view
    payload = {"screening": {"total_screened": None, "analysis_status": "",
                             "analysis_at": None},
               "markets": [{"country": "مصر", "iso3": "EGY", "iso2": None,
                            "score": None, "score_confidence": None,
                            "rationale_components": {},
                            "tags": [], "transit_hub": False,
                            "prices": ["not-a-dict"], "competitors": None,
                            "buyers": [{"name": "مشترٍ", "source": "ويب",
                                        "confidence": 0.4,
                                        "relevance_score": None,
                                        "contacts": "كثير",
                                        "legal_review_required": 0}]}]}
    ex = build_view(_result(executive=payload))["executive"]
    assert ex["screening"]["total_screened"] is None
    m = ex["markets"][0]
    assert m["prices"] == [] and m["competitors"] == []
    # عدد جهات اتصال غير عددي = فجوة معلنة (None)، لا اختلاق عدد.
    assert m["buyers"][0]["contacts"] is None
    assert m["buyers"][0]["legal_review_required"] is False


# ── 3) المشتقّ Word — كامل/ناقص/فجوة كلية ────────────────────────────────────

def test_executive_docx_full_data_renders_pk_zip():
    pytest.importorskip("docx")
    from conftest import docx_all_text
    from silk_render import build_view
    from silk_reports import render_executive_docx
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(_result(executive=_executive_payload()))
    path = _docx_path()
    assert render_executive_docx(view, path) == path
    with open(path, "rb") as fh:
        assert fh.read(2) == b"PK"          # docx = zip حقيقي
    text = docx_all_text(path)
    # الغلاف والأقسام الخمسة بالأرقام الهندية-العربية (لا فهرس لاتينياً).
    assert "التقرير التنفيذي متعدد الأسواق" in text
    for heading in ("١. الخلاصة التنفيذية", "٢. المنتج والتصنيف",
                    "٣. الفرز العالمي", "٤. الأسواق الخمسة بالتفصيل",
                    "٥. حدود التقرير ومصادره"):
        assert heading in text, f"missing heading: {heading}"
    # سطر الفرز بعدد الأسواق المفروزة.
    assert "فُرزت 38 سوقاً عالمياً" in text
    # جدول الأسعار والمنافسين والمشترين ببياناتها.
    assert "علامة منافسة أ" in text and "إيران" in text
    assert "مستورد أغذية — شنغهاي" in text
    # وسم محور العبور ⚠ للسوق الموسوم.
    assert "⚠ محور عبور" in text
    # الأساس التجاري بالاسم العربي للمكوّن + مصدره (لا مفتاح داخلي خام).
    assert "حجم واردات السوق" in text and "UN Comtrade" in text
    assert "market_size" not in text
    # السرد بلا كسر ثقة خام — عبارة الثقة البشرية حاضرة.
    assert "ثقة التصنيف" in text
    # لافتة TEST RUN للتشغيلة الموسومة SILK_HERMETIC.
    assert "TEST RUN" in text


def test_executive_docx_partial_data_declares_gap_lines():
    """أسعار فارغة => سطر «سعر غير مرصود» (سلسلة العقد الحرفية)؛ مشترون
    فارغون => «لا مشترون مرصودون بعد لهذا السوق». لا صفوف مخترعة."""
    pytest.importorskip("docx")
    from conftest import docx_all_text
    from silk_render import build_view
    from silk_reports import render_executive_docx
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(_result(executive=_executive_payload()))
    path = _docx_path()
    render_executive_docx(view, path)
    text = docx_all_text(path)
    assert "سعر غير مرصود" in text                      # العقد الحرفي القائم
    assert "لا مشترون مرصودون بعد لهذا السوق" in text   # فجوة المشترين المعلنة


def test_executive_docx_total_gap_renders_without_crash():
    """نموذج فجوة كلية: فرز غير مرصود + بلا أسواق إطلاقاً — يُصيَّر بلا انهيار
    ويعلن فجوتيه (لا ترتيب مخترَع ولا عدد مختلَق)."""
    pytest.importorskip("docx")
    from conftest import docx_all_text
    from silk_render import build_view
    from silk_reports import render_executive_docx
    os.environ["SILK_HERMETIC"] = "1"
    payload = {"screening": {"total_screened": None, "analysis_status": "",
                             "analysis_at": None}, "markets": []}
    view = build_view(_result(executive=payload, with_market=False))
    path = _docx_path()
    render_executive_docx(view, path)
    with open(path, "rb") as fh:
        assert fh.read(2) == b"PK"
    text = docx_all_text(path)
    assert "عدد الأسواق المفروزة غير مرصود" in text
    assert "لا أسواق مرشّحة مرصودة بعد" in text


# ── 4) حكم واحد لا حكمان ─────────────────────────────────────────────────────

def test_executive_docx_single_authoritative_verdict_only():
    """حكم §8 (view["decision"]) وحده في المشتقّ التنفيذي: ترجمته العربية
    الواحدة حاضرة، لا رمز آلة خام، ولا ترجمة حكم الجورية المخالف (NO-GO) —
    الجورية سطر كفاية بيانات فقط."""
    pytest.importorskip("docx")
    from conftest import docx_all_text
    from silk_render import build_view
    from silk_reports import render_executive_docx
    os.environ["SILK_HERMETIC"] = "1"
    view = build_view(_result(executive=_executive_payload()))
    assert view["decision"]["verdict"] == "CONDITIONAL-GO"
    path = _docx_path()
    render_executive_docx(view, path)
    text = docx_all_text(path)
    assert "دخول مشروط" in text                 # ترجمة CONDITIONAL-GO الواحدة
    assert "CONDITIONAL-GO" not in text         # لا رمز آلة خام
    assert "NO-GO" not in text                  # لا حكم جورية ثانٍ
    assert "عدم الدخول حالياً" not in text      # ولا ترجمته
    assert "كفاية البيانات" in text             # الجورية سطر كفاية فقط


# ── 5) حارس الإنتاج ──────────────────────────────────────────────────────────

def test_executive_docx_production_clean_guard_refuses():
    """أثر برهاني (MagicMock) في نموذج غير موسوم SILK_HERMETIC = رفض التوليد
    بصوت عالٍ — لا تقرير تنفيذي مسموماً بصمت."""
    pytest.importorskip("docx")
    from silk_render import build_view
    from silk_reports import render_executive_docx
    payload = _executive_payload()
    payload["markets"][0]["buyers"][0]["name"] = "MagicMock buyer"
    os.environ.pop("SILK_HERMETIC", None)
    view = build_view(_result(executive=payload))
    assert view.get("test_run") is False
    with pytest.raises(RuntimeError, match="MagicMock"):
        render_executive_docx(view, _docx_path())

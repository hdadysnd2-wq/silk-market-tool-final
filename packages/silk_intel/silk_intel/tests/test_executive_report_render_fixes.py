"""اختبارات إصلاحات تصيير التقرير التنفيذي (C10/C11/C12).

المسار التنفيذي المغذّى من المنصّة: السوق الأعلى بلا هيئة محلفين وبلا قرار
محرّك موزون (score/verdict غائبان صراحةً)، فيسقط `silk_render._decision`
لتراجُع تغطية الجورية. الثوابت المُختبَرة:

- C10: §١ الخلاصة التنفيذية لا تعرض سطر السباكة «لماذا: تغطية الوكلاء 0/0
  وفجوات: لا شيء» على تقرير يُعلن فجوات في §٥ — يُستبدَل بإعلان فجوةٍ صادق
  («مرحلة التوليف المرجَّحة لم تُشغَّل …»)، بلا اختراع حكمٍ ثانٍ.
- C11: مفردات فرز المنصّة (enriched/none/…) تُعرَّب في السرد — لا كلمة
  إنجليزية خام؛ وأي حالة غير معروفة → بديل عربي آمن.
- C12: مفاتيح المزوّدين الداخلية (world_trade/serpapi_shopping/…) تُترجَم
  إلى أسماء مصادر عمومية عربية أينما ظهرت (سطر الأساس + جداول الأسواق + أثر §٥).
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _no_synthesis_result(status: str) -> dict:
    """نتيجة محرّك بمسارٍ تنفيذيٍّ مغذّى من المنصّة — السوق الأعلى بلا jury
    وبلا decision (تراجُع _decision)، وعرض executive بمفردات فرزٍ منصّية
    ومفاتيح مزوّدين خام."""
    at = "2026-08-01"

    def _rc(value, source):
        return {"value": value, "source": source, "confidence": 0.85,
                "note": "", "retrieved_at": at}

    return {
        "product": "تمور", "hs_code": "080410", "hs_confidence": 0.9,
        "year": 2023, "classified": True,
        # السوق الأعلى بلا هيئة محلفين وبلا قرار محرّك موزون: يسقط _decision
        # لتراجُع التغطية (verdict فارغ، بلا سطر كفاية) — شرط تفعيل C10.
        "markets": [{
            "country": "الصين", "iso3": "CHN",
            "total_score": None, "confidence": None, "components": {},
            "quality_flags": ["بيانات الطلب غير مرصودة لهذا السوق",
                              "أسعار المنافسين غير مرصودة لهذا السوق"],
        }],
        "executive": {
            "screening": {"total_screened": 38, "analysis_status": status,
                          "analysis_at": f"{at}T00:00:00Z"},
            "markets": [{
                "country": "الصين", "iso3": "CHN", "iso2": "CN",
                "score": 0.62, "score_confidence": 0.72,
                "rationale_components": {
                    "market_size": _rc(6.0e7, "world_trade"),
                    "saudi_position": _rc(30.0, "world_trade"),
                },
                "tags": ["سوق كبير"], "transit_hub": False,
                "prices": [{"competitor": "علامة منافسة أ", "price": 12.5,
                            "currency": "USD", "store": "متجر إلكتروني",
                            "url": "https://shop.sample/a",
                            "source": "serpapi_shopping",
                            "confidence": 0.6, "retrieved_at": at}],
                "competitors": [{"exporter_name": "إيران", "share_pct": 50.0,
                                 "value_usd": 3.0e7, "source": "world_trade",
                                 "confidence": 0.9, "retrieved_at": at}],
                "buyers": [{"name": "مستورد أغذية — شنغهاي",
                            "source": "serpapi_shopping", "confidence": 0.5,
                            "relevance_score": 0.8, "contacts": 2,
                            "legal_review_required": False}],
            }],
        },
    }


def _render(result: dict) -> str:
    from silk_render import build_view
    from silk_reports import render_executive_docx
    os.environ["SILK_HERMETIC"] = "1"          # يُستعاد عبر fixture conftest
    view = build_view(result)
    # شرط C10 مُحقَّق بنيوياً: لا حكم صادر ولا بوابة كفاية محرّك موزون.
    assert not view["decision"].get("verdict")
    assert not view["decision"].get("sufficiency")
    path = os.path.join(tempfile.mkdtemp(), "executive.docx")
    assert render_executive_docx(view, path) == path
    with open(path, "rb") as fh:
        assert fh.read(2) == b"PK"              # docx = zip حقيقي
    from conftest import docx_all_text
    return docx_all_text(path)


def test_executive_no_synthesis_shows_honest_gap_not_coverage_plumbing():
    """C10: تقريرٌ تنفيذيّ ناجحٌ بلا مرحلة توليفٍ مرجَّحة لا يعرض عبارة
    «تغطية الوكلاء 0/0 وفجوات: لا شيء» المضلِّلة — يُعلن الفجوة الصادقة، مع
    بقاء الشارة «تعذّر إصدار توصية» (لا حكم ثانٍ يُخترَع)."""
    pytest.importorskip("docx")
    from silk_reports import _EXEC_NO_SYNTHESIS_WHY
    text = _render(_no_synthesis_result("enriched"))
    # سطر السباكة المضلِّل غائب تماماً (لا تركيبة «تعذّر … + فجوات: لا شيء»).
    assert "فجوات: لا شيء" not in text
    assert "تغطية الوكلاء" not in text
    # إعلان الفجوة الصادق حاضر بدلاً منه.
    assert _EXEC_NO_SYNTHESIS_WHY in text
    assert "مرحلة التوليف المرجَّحة لم تُشغَّل" in text
    # والتقرير فعلاً يُعلن فجواتٍ في §٥ (فلم تكن «لا شيء» صادقة أصلاً).
    assert "لا حدود مسجّلة لهذا التحليل" not in text


def test_executive_platform_status_vocab_is_arabic_not_raw_english():
    """C11: مفردات فرز المنصّة تُعرَّب في السرد — لا 'enriched' خاماً."""
    pytest.importorskip("docx")
    text = _render(_no_synthesis_result("enriched"))
    assert "enriched" not in text
    assert "أُثريت الأسواق" in text
    # حالة «بلا تحليل» في تشغيلة منفصلة — لا 'none' خاماً.
    text_none = _render(_no_synthesis_result("none"))
    assert "none" not in text_none
    assert "لم يبدأ التحليل" in text_none


def test_executive_source_keys_render_as_public_arabic_labels():
    """C12: مفاتيح المزوّدين الخام لا تظهر على وجه العميل — تُترجَم لأسماء
    مصادر عمومية عربية (سطر الأساس + جداول الأسواق + أثر §٥)."""
    pytest.importorskip("docx")
    text = _render(_no_synthesis_result("enriched"))
    assert "world_trade" not in text
    assert "serpapi_shopping" not in text
    assert "الأمم المتحدة (كومتريد)" in text     # world_trade → عمومي
    assert "رصد متاجر إلكترونية" in text          # serpapi_shopping → عمومي


def test_exec_status_ar_maps_full_platform_vocabulary():
    """C11 وحدةً: خريطة الحالة تغطي مفردات المنصّة، وغير المعروف بديلٌ عربيٌّ
    آمن (لا مفتاح إنجليزي خام أبداً)."""
    from silk_reports import _exec_status_ar
    assert _exec_status_ar("none") == "لم يبدأ التحليل"
    assert _exec_status_ar("classified") == "صُنِّف المنتج"
    assert _exec_status_ar("ranked") == "فُرزت الأسواق"
    assert _exec_status_ar("enriched") == "أُثريت الأسواق"
    assert _exec_status_ar("deepened") == "عُمّقت الأسواق"
    # المفردات العامة القائمة ما زالت تعمل.
    assert _exec_status_ar("complete") == "مكتمل"
    assert _exec_status_ar("running") == "قيد التنفيذ"
    # حالة غير معروفة → بديل آمن، لا المفتاح الخام؛ الفارغ → «غير مسجَّلة».
    assert _exec_status_ar("frobnicated") == "حالة غير معروفة"
    assert _exec_status_ar("") == "غير مسجَّلة"


def test_exec_source_label_maps_provider_keys():
    """C12 وحدةً: مفاتيح المزوّدين → أسماء عمومية؛ المفتاح غير المعروف يمرّ
    كما ورد (لا انهيار، لا اختلاق)."""
    from silk_reports import _exec_source_label
    assert _exec_source_label("world_trade") == "الأمم المتحدة (كومتريد)"
    assert _exec_source_label("comtrade") == "الأمم المتحدة (كومتريد)"
    assert _exec_source_label("worldbank") == "البنك الدولي"
    assert _exec_source_label("serpapi_shopping") == "رصد متاجر إلكترونية"
    assert _exec_source_label("maps") == "خرائط الويب"
    assert _exec_source_label("importer_intel") == "سجلات شحن مدفوعة"
    # اسم عمومي مرصود مسبقاً يمرّ كما ورد (لا يُترجَم مرتين).
    assert _exec_source_label("UN Comtrade") == "UN Comtrade"
    # مفتاح غير معروف يمرّ كما ورد.
    assert _exec_source_label("some_new_provider") == "some_new_provider"

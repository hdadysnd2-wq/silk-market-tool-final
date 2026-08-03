"""D2 (SPEC-v2) — إنقاذ بنود المحلل الموسومة بمرادف فئة خارج القائمة الحرفية.

البند D2: التقاطعات الخمس تظهر «بلا أدلة كافية» رغم مساهمة البعثات. #107
شحن تشخيصاً ذاتياً يميّز الأسباب الثلاثة (فشل نداء / بلا وسم / وسم بفئة خارج
القائمة) لكنه أعلن إصلاح السبب الجذري NOT DONE. هذا الملف يقفل إصلاح أحد
الأسباب الثلاثة الحتمية والآمن بلا مدوّنة حيّة: **وسم بمرادف صريح** (مثل
[pricing] بدل [price_competitiveness]) — يُنقَذ عبر خريطة مرادفات تحفّظية.

يُحترَم نمط الحادثة #8 (#107): بند **بلا** وسم [فئة] يبقى مُشخَّصاً لا
مُخمَّناً — لا نخمّن محتوى بند غير موسوم. وعقد عدم الاختلاق يبقى: الإنقاذ
يصنّف بنداً حقيقياً موجوداً، لا يخترع قيمة.

Run: python3 -m pytest tests/test_analyst_synonym_rescue_d2.py -q
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mk(findings, failed=False, summary="تحليل"):
    from silk_agents import AgentReport
    return AgentReport("LLMAgent:market_analyst", findings, failed, summary)


def _dp(value, note):
    from silk_data_layer import DataPoint
    return DataPoint(value, "src", 0.7, note)


def _run(report):
    import silk_market_analyst as A
    from silk_market_resolver import resolve_market
    ref, _ = resolve_market("Netherlands")
    with patch.object(A, "run_llm_agent", return_value=report):
        return A.analyze_market(ref, "تمور", {}, hs_code="080410")


def test_synonym_tag_is_rescued_into_canonical_category():
    """[pricing] (مرادف) => يُصنَّف price_competitiveness، لا يُسقَط صمتاً."""
    out = _run(_mk([_dp("هامش 12%", "[pricing] تسعير المنافس مقابل تكلفتنا")]))
    assert "price_competitiveness" not in out["missing_categories"]
    assert any(dp.value == "هامش 12%"
               for dp in out["by_category"]["price_competitiveness"])
    assert out["diagnostics"]["synonym_rescued"] >= 1


def test_multiple_synonyms_across_categories():
    """مرادفات متعددة عبر الفئات كلها تُنقَذ — لا خمس تقاطعات فارغة زيفاً."""
    findings = [_dp("طلب مرصود", "[consumer_demand] استهلاك"),
                _dp("تكلفة دخول", "[cost] جمرك وتعريفة"),
                _dp("قناة", "[distribution] موزّع محلي"),
                _dp("منافسة سعرية", "[competition] سعر الرفّ")]
    out = _run(_mk(findings))
    m = out["missing_categories"]
    for c in ("demand", "entry_cost", "entry_door", "price_competitiveness"):
        assert c not in m, f"{c} لم يُنقَذ رغم مرادف صريح: {m}"


def test_exact_canonical_tags_still_bin_without_counting_as_rescued():
    """الوسوم الحرفية الصحيحة تبقى تُصنَّف مباشرة (طبيعياً) ولا تُحتسَب
    إنقاذاً — الإنقاذ للمرادفات فقط."""
    out = _run(_mk([_dp("طلب", "[demand] ثقافة استهلاك"),
                    _dp("سعر", "[price_competitiveness] هامش")]))
    assert out["diagnostics"]["synonym_rescued"] == 0
    assert "demand" not in out["missing_categories"]
    assert "price_competitiveness" not in out["missing_categories"]


def test_untagged_finding_still_diagnosed_not_guessed():
    """احترام نمط #8 (#107): بند بلا وسم [فئة] يبقى غير مصنَّف — لا تخمين
    محتوى. binned يبقى 0 والسبب findings_present_but_uncategorized."""
    out = _run(_mk([_dp("واردات 61 مليون", "رقم بلا وسم فئة")]))
    d = out["diagnostics"]
    assert d["binned"] == 0 and d["uncategorized"] == 1
    assert d["all_missing_cause"] == "findings_present_but_uncategorized"


def test_unknown_synonym_is_not_forced_into_a_category():
    """مرادف غير معروف (فئة مخترعة لا تقابل أياً من الخمس) لا يُقحَم — تحفّظ
    صارم ضد التصنيف الكاذب."""
    out = _run(_mk([_dp("قيمة", "[weather_forecast] لا علاقة")]))
    assert all(len(v) == 0 for v in out["by_category"].values())
    assert out["diagnostics"]["synonym_rescued"] == 0


def test_synonym_rescue_never_fabricates_value():
    """الإنقاذ يصنّف بنداً حقيقياً فقط — القيمة None (فجوة معلنة) تبقى None،
    لا صفر مختلق ولا بند جديد."""
    out = _run(_mk([_dp(None, "[pricing] تسعير المنافسين غير مرصود")]))
    dps = out["by_category"]["price_competitiveness"]
    assert dps and dps[0].value is None  # لا اختلاق قيمة

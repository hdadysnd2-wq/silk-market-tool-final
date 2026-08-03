"""قفلُ DEF-2 — عضويةُ الكُتل التجارية من مصدرٍ واحدٍ لا تتشعّب (LESSONS 63).

الباعث (التدقيق المعماري ٢٠٢٦-٠٧-٢٤، DEF-2): قائمةُ الاتحاد الأوروبي كانت
مكتوبةً صلباً في ثلاثة مواضعَ بقيمٍ متباينة — `silk_requirements_agent._EU` حملت
١٥ عضواً فقط بينما `silk_tariffs_agent._EU_ISO3` و`silk_eurostat_agent`
حملتا ٢٧ — فسقطت سلسلةُ الامتثال الأوروبية بصمتٍ عن اثنتي عشرة دولةً عضواً
(المجر/رومانيا/بلغاريا/…) في مسار الاشتراطات وحده. هذا القفل يضمن:
مصدرٌ واحدٌ (`silk_blocs`)، وكلُّ مستهلكٍ يشير إليه بالهُويّة نفسها، فلا تشعّبَ.

Lock for DEF-2: trade-bloc membership has ONE source; no consumer may diverge.
Hermetic — pure constants, no network.
"""
import silk_blocs
import silk_requirements_agent as reqs
import silk_tariffs_agent as tariffs
import silk_eurostat_agent as euro

# الدولُ الاثنتا عشرة التي كانت غائبةً عن `_EU` (١٥→٢٧) — لبّ العيب.
_FORMERLY_MISSING = {
    "BGR", "HRV", "CYP", "EST", "HUN", "LVA", "LTU", "LUX", "MLT",
    "ROU", "SVK", "SVN",
}


def test_eu27_has_all_twenty_seven_members():
    assert len(silk_blocs.EU27) == 27
    assert _FORMERLY_MISSING <= silk_blocs.EU27


def test_all_eu_consumers_are_the_single_source_by_identity():
    """كلُّ مستهلكٍ هو نفسُ الكائن — لا نسخةٌ قد تتشعّب لاحقاً."""
    assert reqs._EU is silk_blocs.EU27
    assert tariffs._EU_ISO3 is silk_blocs.EU27


def test_all_eu_consumers_agree_by_value():
    """يوروستات = EU27 ∪ EFTA؛ ومجموعتُه الأوروبيةُ الصِّرفة = EU27 تماماً."""
    assert euro.EU_EFTA_MARKETS == silk_blocs.EU27 | silk_blocs.EFTA
    assert (euro.EU_EFTA_MARKETS - silk_blocs.EFTA) == silk_blocs.EU27


def test_all_gcc_consumers_are_the_single_source():
    assert reqs._GCC is silk_blocs.GCC
    assert tariffs._GCC_MEMBERS is silk_blocs.GCC
    assert len(silk_blocs.GCC) == 6


def test_formerly_missing_members_now_get_full_codification_tier():
    """المجر/رومانيا/… تنال «مقنّن بالكامل» (سلسلة EUR-Lex) لا «موثّق جزئياً»."""
    for iso in _FORMERLY_MISSING:
        tier, _note = reqs.codification_tier(iso)
        assert tier == "مقنّن بالكامل", f"{iso} سقط للطبقة الجزئية"


def test_formerly_missing_members_match_eu_requirement_rows():
    """بندُ مرجعٍ موسومٌ «EU» ينطبق الآن على عضوٍ كان غائباً (المجر)."""
    eu_row = {"market": "EU", "category": "all", "direction": "import"}
    assert reqs._matches(eu_row, "HUN", "all", "import", animal=False)
    assert reqs._matches(eu_row, "ROU", "food", "import", animal=False)


def test_eurostat_eligibility_covers_formerly_missing_members():
    for iso in _FORMERLY_MISSING:
        assert euro._eligible(iso) is True


def test_no_consumer_hardcodes_a_raw_eu_or_gcc_literal():
    """حارسٌ بنيويّ (نسخةُ لِنتة G5 اليدوية): لا مستهلكٍ يُعيد تعريفَ مجموعةٍ
    خامٍّ من رموز ISO للاتحاد — يجب أن يستوردَ `silk_blocs`."""
    import inspect
    for mod in (reqs, tariffs, euro):
        src = inspect.getsource(mod)
        assert "silk_blocs" in src, f"{mod.__name__} لا يشير للمصدر الواحد"

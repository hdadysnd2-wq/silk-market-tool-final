"""بلاغ حي إنتاجي (تمور/هولندا، اكتمل بتكلفة $1.6): حارس تصدير العميل (client
docx) رفض إحدى محاولات سابقة بـ501، وأثناء التحقيق (بلا توفّر نصّ الرفض
الخام بعد) اكتُشف — بتشغيل الشيفرة الفعلية على نصّ التقرير المُلصَق حرفياً —
فجوة أخطر: صيغ المثنى/الضمير المتصل لكلمة "بعثة" (مصطلح تشغيلي داخلي ممنوع)
تُفلِت تماماً من الحارس القديم `بعث(?:ة|ات)` لأن تاء التأنيث المربوطة ة
تتحوّل نحوياً إلى تاء مفتوحة ت عند اتصال أي لاحقة — فـ"بعثتي"/"بعثتا"/
"بعثتها" لا تحوي حرفياً السلسلة الفرعية "بعثة" ولا "بعثات". النتيجة: هذه
الصيغ لم تكن تُكتشَف كمصطلح ممنوع ولا تُحوَّل لمفردة تجارية — بل تصل متن
العميل حرفياً كما هي (تسريب تِلِمِتري صامت، لا رفض، وهو أسوأ من 501 واضح).
نفس الفجوة النحوية أصابت "الفجوات المعلنة" (بأداة التعريف) مقابل الصيغة
غير المعرَّفة "فجوات معلنة" المكتوبة في الحارس.

Run: python3 -m pytest tests/test_client_docx_mission_morphology_leak.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_reports as sr

# السلاسل الحرفية من التقرير الحيّ المُلصَق (تمور/هولندا) — لا إعادة صياغة.
_LIVE_DUAL_MISSION = ('اعتمد هذا التقرير على اثنتي عشرة بعثة تحليلية متخصصة، '
                     'أنتجت غالبيتها أدلة مستشهَداً بها فعلياً باستثناء '
                     'بعثتي "الأخبار والمخاطر" و"فجوات الفرص" اللتين واجهتا '
                     'عطلاً تقنياً في تفسير مخرجات النموذج كـJSON.')
_LIVE_DEFINITE_GAP = ("| الفجوات المعلنة | أخبار المخاطر، فجوات الفرص |")


def test_dual_mission_form_is_now_detected_as_forbidden():
    # معزول عمداً عن أي "بعثة" مفردة مجاورة (النص الكامل _LIVE_DUAL_MISSION
    # يحوي "بعثة" مفردة أيضاً فيُكتشَف حتى بالحارس القديم — لا يثبت شيئاً عن
    # صيغة المثنى تحديداً). هذا المقطع يحوي "بعثتي" فقط، بلا أي صيغة مفردة.
    isolated = 'باستثناء بعثتي "الأخبار والمخاطر" و"فجوات الفرص"'
    hits = sr._client_forbidden_hits(isolated)
    assert any(h.startswith("mission:") for h in hits), (
        "بعثتي (صيغة المثنى) يجب أن تُكتشَف الآن — كانت تُفلِت تماماً "
        f"من الحارس. hits={hits}")


def test_dual_mission_form_gets_converted_not_left_leaking_verbatim():
    sanitized = sr._client_sanitize(_LIVE_DUAL_MISSION)
    assert "بعثتي" not in sanitized, (
        "التسريب الفعلي المُكتشَف: (بعثتي) بقيت بلا تحويل حرفياً في النص "
        f"بعد التطهير — sanitized={sanitized!r}")
    # لا مصطلح ممنوع ينجو من التطهير الكامل (الحارس النهائي لن يرفض هذا النص).
    assert sr._client_forbidden_hits(sanitized) == []


def test_definite_article_declared_gap_is_now_detected_and_converted():
    hits = sr._client_forbidden_hits(_LIVE_DEFINITE_GAP)
    assert any(h.startswith("declared_gap:") for h in hits)
    sanitized = sr._client_sanitize(_LIVE_DEFINITE_GAP)
    assert "الفجوات المعلنة" not in sanitized
    assert sr._client_forbidden_hits(sanitized) == []


def test_other_dual_and_pronoun_suffixed_mission_forms_also_covered():
    for text, forbidden_substring in [
        ("بعثتا الأخبار والمخاطر واجهتا عطلاً", "بعثتا"),
        ("توقفت بعثتها عن العمل", "بعثتها"),
        ("بعثتهم لم تكتمل بعد", "بعثتهم"),
    ]:
        sanitized = sr._client_sanitize(text)
        assert forbidden_substring not in sanitized, (
            f"{forbidden_substring!r} still leaks verbatim: {sanitized!r}")
        assert sr._client_forbidden_hits(sanitized) == []


def test_preexisting_singular_and_plural_conversions_unchanged():
    """§2.2 (أمر العمل الرئيس): «بعثة»/«بعثات» لم تعد تُحوَّل إلى «مسار بحث»
    (نسبة داخلية لمسار بحث) بل إلى صياغة محايدة «جمع البيانات» — لا كشف
    بنية. باقي التحويلات (الفجوات المعلنة) كما هي."""
    assert sr._client_sanitize("بعثة واحدة") == "جمع البيانات واحدة"
    assert sr._client_sanitize("البعثات الاثنتي عشرة") == "العمليات جمع البيانات الاثنتي عشرة"
    assert sr._client_sanitize("وهي فجوة معلنة صريحة") == "وهي بند يحتاج تحققاً صريحة"
    assert sr._client_sanitize("فجوات معلنة عديدة") == "بنود تحتاج تحققاً عديدة"
    # §2.2: لا «مسار بحث» في المخرَج بعد التطهير.
    assert "مسار بحث" not in sr._client_sanitize("بعثة وبعثات ومهمّة")


def test_full_live_report_excerpt_survives_client_docx_guard_cleanly():
    """محاكاة الحارس النهائي (_client_assert_clean) على نص التقرير الحيّ
    الكامل تقريباً — كان يُفلِت التسريب صامتاً؛ الآن يُطهَّر بالكامل."""
    sanitized = sr._client_sanitize(_LIVE_DUAL_MISSION + "\n" + _LIVE_DEFINITE_GAP)
    assert sr._client_forbidden_hits(sanitized) == []

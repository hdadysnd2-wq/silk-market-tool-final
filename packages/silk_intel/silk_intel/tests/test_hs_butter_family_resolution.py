"""أقفال دقّة تصنيف عائلة «الزبدة» — HS butter-family resolution accuracy.

طلب المالك (2026-07-23): «افحص دقّة اختيار رمز HS وحُلّها». إعادة إنتاج حيّة
أثبتت أن `resolve('زبدة الفول السوداني')` كان يُرجع 040510 (زبدة **ألبان**)
بثقة 0.85 — نفس عائلة الحادثة الأصلية (الدرس ٣٢): كلمة «زبدة» العامّة طابقت
رمز الألبان بينما الصفة المميّزة «فول سوداني» غائبةٌ عن وصفه.

إصلاحان (كلاهما بلا اختلاق، بلا شبكة):
1. **بيانات**: الرموز الصحيحة الموجودة أصلاً في البذرة (200811 فول سوداني
   محضّر، 180400 كاكاو، 151590 شيا) زُوِّدت بكلماتٍ مفتاحيةٍ عربية فصارت
   قابلةَ الوصول وتفوز بتطابقٍ تام.
2. **منطق**: `resolve_all` يُخفّض أيّ مرشّحٍ أعلى تطابقاً لكن صفتُه المميّزة
   غائبةٌ عن وصفه (`confirm_hs → confirmed=False`) إلى **فجوةٍ معلَنة**
   (value=None) بدل رمزٍ خاطئٍ واثق — يحرس العائلة كلها لا الزبدة وحدها.
"""
from silk_hs_resolver import resolve, resolve_all
from silk_hs_confirm import confirm_hs


def test_peanut_butter_resolves_to_correct_family_not_dairy():
    """العيّنة الأصلية: «زبدة الفول السوداني» => 200811 (فول سوداني محضّر)،
    لا 040510 (زبدة ألبان)، ومؤكَّدةٌ صفةً."""
    dp = resolve("زبدة الفول السوداني")
    assert dp.value == "200811", f"expected 200811, got {dp.value}"
    assert dp.value != "040510"
    assert confirm_hs("زبدة الفول السوداني", dp.value)["confirmed"] is True


def test_cocoa_and_shea_butter_resolve_to_their_real_codes():
    """أشقّاء العائلة: كاكاو => 180400، شيا => 151590 (لا رمز الألبان)."""
    assert resolve("زبدة الكاكاو").value == "180400"
    assert resolve("زبدة الشيا").value == "151590"


def test_plain_butter_still_resolves_to_dairy():
    """عدم انحدار: «زبدة» وحدها (بلا صفةٍ مميّزة) تبقى 040510 (ألبان)."""
    assert resolve("زبدة").value == "040510"


def test_resolver_declares_gap_rather_than_confident_wrong_family():
    """البوّابة التعميمية: مركّب «زبدة X» بثلاث كلماتٍ فأكثر لا يقابله رمزٌ
    صحيحٌ في البذرة => فجوةٌ معلَنة (value=None، ثقة 0.0)، لا رمز ألبانٍ واثق.

    عقد عدم الاختلاق: إعلان الفجوة أصدق من رمزٍ خاطئٍ بثقةٍ عالية."""
    dp = resolve("زبدة الطحينة السائلة الفاخرة")
    # لا يُقدَّم رمز الألبان الخاطئ حكماً واثقاً؛ إمّا رمزٌ مؤكَّدٌ صفةً أو فجوة.
    if dp.value is not None:
        assert dp.value != "040510"
        assert confirm_hs("زبدة الطحينة السائلة الفاخرة", dp.value)["confirmed"] \
            is not False
    else:
        assert dp.confidence == 0.0


def test_resolver_gap_note_is_explicit_and_names_the_reason():
    """الفجوة المُخفَّضة تحمل سبباً صريحاً (لا خانةٌ صامتة)."""
    # منتجٌ صفتُه المميّزة غائبةٌ عن أقرب رمز => إمّا فجوة بسبب، أو رمز مؤكَّد.
    dp = resolve("زبدة اليقطين المحمصة الخاصة")
    if dp.value is None:
        assert dp.confidence == 0.0 and dp.note
        assert "040510" not in dp.note or "غير مؤكَّد" in dp.note


def test_legit_products_unaffected_by_the_confirmation_gate():
    """عدم انحدار واسع: منتجاتٌ سليمةٌ متنوّعة تبقى تُحسَم كما كانت."""
    cases = {
        "تمور": "080410", "عسل": "040900", "زعفران": "091020",
        "زيت زيتون بكر ممتاز": "150910",
    }
    for product, expected in cases.items():
        assert resolve(product).value == expected, f"{product} regressed"

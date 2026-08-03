"""قفل الرُتبة الموثّقة للتعريفة الخليجية — GCC documented-agreement tariff tier.

بلاغ حي (تشغيلة زبدة الفول السوداني/الكويت 2026-07-23): فجوة معلنة نصّها
«التعريفة لرمز HS 200811 من السعودية للكويت غير متاحة WITS — يفترض أنها صفر
بموجب GCC لكن لا توثيق رقمي فعلي». المرجع الموثّق موجود فعلاً في الريبو
(`data/agreements_l1.csv`: صف GCC للكويت — «إعفاء كامل بين الأعضاء»، مصدر
GCC secretariat) لكن سلسلة `tariff_with_fallback` لم تكن تستشيره.

القانون: بعد فشل المصدرين الحيّين (WTO TTD ثم WITS)، إن كان **كلا** الطرفين
عضوين في الاتحاد الجمركي الخليجي وللسوق صفّ GCC موثّق في مرجع الاتفاقيات،
تُخدَم تعريفة 0.0 **موسومة مرجعاً قانونياً موثّقاً لا رصداً تعريفياً حياً**
(status="documented_agreement"، المصدر والرابط من صفّ CSV نفسه، والملاحظة
تصرّح بشرط شهادة المنشأ). خارج هذا الشرط الضيّق تبقى الفجوة معلنة كما هي —
عضوية GAFTA («شبه كامل») لا تكفي لرقم، والصفر المختلَق ممنوع كما كان.

هرمتي: الشبكة مقطوعة عبر patch على requests.get — الرُتبة الموثّقة لا تحتاج
أي نداء خارجي (قراءة CSV محلية فقط).
Run: python3 -m pytest tests/test_tariff_gcc_documented_fallback.py -q
"""
from unittest.mock import patch

from silk_data_layer import DataPoint
from silk_tariffs_agent import tariff_with_fallback


def _dead_network():
    """كل نداء HTTP يفشل — يدفع WTO (بلا مفتاح: تدهور فوري) وWITS للفجوة."""
    return patch("requests.get", side_effect=OSError("network blocked in test"))


def test_kwt_from_sau_serves_documented_gcc_exemption_when_live_sources_fail():
    """حالة الكويت الحية بالضبط: WTO+WITS فاشلان، الطرفان خليجيان => 0.0
    موثّقة من مرجع الاتفاقيات، لا فجوة ولا صفر مختلَق."""
    with _dead_network():
        dp = tariff_with_fallback("200811", "KWT", "SAU")
    assert dp.value == 0.0
    assert dp.source == "GCC secretariat"
    assert dp.status == "documented_agreement"
    assert dp.confidence > 0.0
    assert "شهادة منشأ" in dp.note
    assert "gcc-sg.org" in dp.note


def test_non_gcc_market_stays_declared_gap():
    """سوق غير خليجية (هولندا) — الرُتبة الموثّقة لا تنطبق؛ الفجوة تبقى."""
    with _dead_network():
        dp = tariff_with_fallback("200811", "NLD", "SAU")
    assert dp.value is None
    assert dp.confidence == 0.0


def test_non_gcc_partner_stays_declared_gap():
    """شريك غير خليجي (الصين -> الكويت) — الإعفاء البيني لا يشمله؛ فجوة."""
    with _dead_network():
        dp = tariff_with_fallback("200811", "KWT", "CHN")
    assert dp.value is None
    assert dp.confidence == 0.0


def test_gafta_membership_alone_is_not_enough_for_a_number():
    """عضوية GAFTA وحدها («إعفاء شبه كامل على غالب السلع») لا تُنتِج رقماً —
    مصر عضو GAFTA لا GCC؛ ادّعاء 0.0 هنا اختلاق، تبقى فجوة معلنة."""
    with _dead_network():
        dp = tariff_with_fallback("200811", "EGY", "SAU")
    assert dp.value is None
    assert dp.confidence == 0.0


def test_live_wits_rate_still_wins_over_documented_tier():
    """المصدر الحي مقدَّم دائماً: WITS ناجح => تعريفته تُخدَم لا المرجع الموثّق."""
    live = DataPoint(5.0, "World Bank WITS", 0.85, "reported 5.0%", "2026-07-23")
    with patch("silk_tariffs_agent.applied_tariff", return_value=live), \
         _dead_network():
        dp = tariff_with_fallback("200811", "KWT", "SAU")
    assert dp.value == 5.0
    assert dp.source == "World Bank WITS"

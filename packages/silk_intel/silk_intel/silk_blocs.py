"""مصدرٌ واحدٌ لعضوية الكُتل التجارية — single source of truth for trade-bloc
membership ISO3 sets (EU27 · EFTA · GCC).

**الباعث (DEF-2، التدقيق المعماري ٢٠٢٦-٠٧-٢٤):** كانت قائمةُ الاتحاد الأوروبي
مكتوبةً صلباً في ثلاثة مواضعَ منفصلة بقيمٍ متباينة — `silk_requirements_agent._EU`
(١٥ عضواً فقط)، `silk_tariffs_agent._EU_ISO3` (٢٧، صحيحة)، و
`silk_eurostat_agent.EU_EFTA_MARKETS` (٢٧+EFTA، صحيحة). فسقطت سلسلةُ الامتثال
الأوروبية بصمتٍ عن اثنتي عشرة دولةً عضواً (المجر/رومانيا/…) في مسار الاشتراطات
وحده. عائلةُ الدرس ٢٥/٣٥: قائمةٌ مكتوبةٌ صلباً تتشعّب فتتخصّص المنصّةُ ضمناً.
**الإصلاح:** تعريفٌ واحدٌ هنا، وكلُّ مستهلكٍ يشير إليه — فلا تشعّبَ ممكنٌ بعد.

هذا مصدرٌ انتقاليّ قبل طبقة التعميم (G3/G5): حين تُشتَقّ العضويةُ من ملفّات
البروفايل (`data/market_profiles.json`) عبر مُحلِّلٍ واعٍ بالبروفايل، وتحرسها
لِنتة الترميز الصلب (G5)، تحلّ محلَّ هذا الثابت. حتى ذلك الحين هو نقطةُ الحقيقة
الوحيدة، ويحرسه `tests/test_bloc_lists_single_source.py`.

Single source of truth for trade-bloc ISO3 membership. Interim (pre-G3/G5):
once membership is profile-derived and guarded by the G5 hardcode lint, this
constant is superseded. Stdlib-only, imports nothing — safe to import anywhere.
"""
from __future__ import annotations

# الاتحاد الأوروبي — ٢٧ دولةً عضواً (بعد خروج المملكة المتحدة ٢٠٢٠).
# المصدر: المفوضية الأوروبية، «الدول الأعضاء» — https://european-union.europa.eu/
# principles-countries-history/eu-countries_en (مراجعة ٢٠٢٦-٠٧-٢٤).
EU27: frozenset[str] = frozenset({
    "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA",
    "DEU", "GRC", "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD",
    "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE",
})

# رابطة التجارة الحرة الأوروبية — أربع دول (آيسلندا/ليختنشتاين/النرويج/سويسرا).
# المصدر: الأمانة العامة لـEFTA — https://www.efta.int/about-efta/the-efta-states
# (مراجعة ٢٠٢٦-٠٧-٢٤). تُغطّيها يوروستات مع EU27 لكنها ليست جزءاً من سلسلة
# الامتثال المرقّمة (EUR-Lex) — تبقى منفصلةً عن EU27.
EFTA: frozenset[str] = frozenset({"ISL", "LIE", "NOR", "CHE"})

# مجلس التعاون الخليجي / الاتحاد الجمركي — ستُّ دول (ثابتُ معاهدة، ميثاق مجلس
# التعاون ٢٠٠٣). المصدر: الأمانة العامة لمجلس التعاون — https://www.gcc-sg.org
# (مراجعة ٢٠٢٦-٠٧-٢٤). السعودية طرفٌ منشأ لكنها عضوٌ للتحقّق الثنائيّ من الإعفاء.
GCC: frozenset[str] = frozenset({"SAU", "ARE", "KWT", "QAT", "BHR", "OMN"})

# اتحادُ EU27 مع EFTA — نطاقُ تغطية يوروستات.
EU_EFTA: frozenset[str] = EU27 | EFTA

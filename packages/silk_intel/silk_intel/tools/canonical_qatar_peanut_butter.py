"""نتيجةُ بحثٍ عميقٍ مموّهةٌ (قطر × HS 200811، زبدة فول سوداني) تُعيد إنتاج
**كلَّ أصناف عيوب بلاغ قطر** قبل الإصلاح — كي تُثبِت البوّابةُ الموسَّعة أنّ
الهوتفكس عالجها فعلاً على تقريرٍ بشكلِ قطرَ الحقيقيّ (لا هولندا وحدها):

- HF1: بندٌ أسنَده مصدران (`IMF WEO` + `World Bank`) وآخرُ (`GCC secretariat` +
  `GAFTA secretariat`) — يمرّان عبر `source_ids` الذرّية لا سلسلةٍ مدموجة.
- HF2: نثرٌ يحمل استشهاداتٍ داخلية «(dp3)»/«(dp3، dp4)» وأرقاماً عشرية
  («7.12م$») — لا خليةٌ تُبتَر داخل رقمٍ ولا قوسٌ فارغٌ يتبقّى.
- HF3: «حجم سوق الفول السوداني الكامل … 497 مليون دولار» مقابل واردات ٧م$ —
  يُوسَم ويُتحفَّظ عليه.
- HF4.3: «Five Group Trading Company» مرشّحٌ غير موثَّقٍ في الجدول، يُذكَر في
  النثر — يُوسَم بالحالة المحافِظة.

مموّهةٌ موسومة (نمط §10.6) — تمرّ عبر مسار العرض الإنتاجيّ الحقيقيّ. ليست
تشغيلةً حيّة (لا مفتاح Claude في البيئة الهرمتية).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_agents import AgentReport
from silk_data_layer import DataPoint
from silk_market_resolver import resolve_market

ref, _ = resolve_market("Qatar")

# نثرُ الكاتب — يحمل عمداً محفّزاتِ العيوب: استشهاداتٍ داخلية «(dpN)»، رقماً
# عشرياً قابلاً للبتر، واسمَ موزّعٍ مرشّحٍ يُذكَر كأنه حقيقة.
REPORT_TEXT = """## 1. الخلاصة التنفيذية

التوصية دخول مشروط. يستورد السوق زبدة الفول السوداني بقيمة 7.12 مليون دولار
سنوياً (dp1)، بمعدّل نموّ مركّب موجب، وصفُّ المورّدين معتدل التركّز فيفتح باباً
لمورّد سعوديّ ينافس بالسعر (dp2، dp3).

## 2. منهجية البحث ونطاقه

اعتمد هذا التقرير على Comtrade وWorld Bank وIMF WEO وGoogle Trends وأمانتَي
GCC وGAFTA. سنة البيانات الأساسية 2023.

## 3. نظرة عامة على السوق وحجمه

بلغت واردات قطر من زبدة الفول السوداني HS200811 نحو 7.12 مليون دولار عام 2023
(UN Comtrade). ويُقدَّر حجم سوق الفول السوداني الكامل في قطر بـ 497 مليون دولار
عام 2025 (dp4) — رقمٌ يقيس فئةً أوسع بكثيرٍ من هذا البند الجمركيّ.

### 3.2 الموزّعون في السوق

من الموزّعين الناشطين Five Group Trading Company، ويُنصَح بالتحقّق قبل التعاقد.

## 4. التنظيم والوصول للسوق

قطر عضوٌ في مجلس التعاون الخليجيّ ومنطقة التجارة الحرة العربية الكبرى، فتتمتّع
واردات المنشأ السعوديّ بإعفاءٍ جمركيّ.
"""


def _f(value, source, confidence, note, source_ids=()):
    return DataPoint(value, source, confidence, note, "2026-07-23",
                     source_ids=tuple(source_ids))


def _rep(name, findings, summary):
    return AgentReport(f"LLMAgent:{name}", findings, False, summary)


# HF1: بندان متعدّدا المصادر — `source` ذرّيّ (الأساسيّ) و`source_ids` القائمة.
gdp_growth = _f(
    "نمو الناتج المحليّ للفرد في قطر مستقرّ", "IMF WEO", 0.85,
    "[demand] مؤشّر اقتصاديّ", source_ids=("IMF WEO", "World Bank"))
agreements = _f(
    "قطر عضوٌ في GCC وGAFTA — إعفاءٌ جمركيّ للمنشأ السعوديّ",
    "GCC secretariat", 0.8, "[entry_cost] عضويّة تكتّلين",
    source_ids=("GCC secretariat", "GAFTA secretariat"))

missions = {
    "trade_flow": _rep("trade_flow", [
        _f(7_120_000.0, "UN Comtrade", 0.9,
           "HS200811 إجمالي استيراد قطر من العالم 2023, USD")],
        "تدفقات تجارية مؤكَّدة"),
    "demographics_economy": _rep("demographics_economy", [
        _f(2_860_000.0, "World Bank", 0.95, "عدد سكان قطر، نسمة، 2023"),
        gdp_growth],
        "مؤشرات مستقرة"),
    "consumer_culture": _rep("consumer_culture", [
        _f("497 مليون دولار", "بحث ويب موجَّه", 0.4,
           "حجم سوق الفول السوداني الكامل في قطر قُدِّر عام 2025 — فئةٌ أوسع")],
        "إشارة حجم سوقٍ واسعة (فئة أوسع)"),
    "tariffs_agreements": _rep("tariffs_agreements", [agreements],
                               "إعفاء جمركيّ عبر تكتّلين"),
    "demand_trends": _rep("demand_trends", [
        _f("اتجاه بحثٍ صاعد على خمس سنوات", "Google Trends", 0.6,
           "موسمية واضحة")], "اتجاه طلب موسمي"),
    "channels_importers": _rep("channels_importers", [
        _f("موزّع مرشّح للتحقّق", "بحث ويب (غير مؤكَّد)", 0.35,
           "[entry_door] مرشّح")], "موزّع محتمل"),
}

analyst_report = AgentReport(
    "LLMAgent:market_analyst",
    [missions["trade_flow"].findings[0], gdp_growth, agreements],
    False, "تحليل التقاطعات مكتمل")

result = {
    "product": "زبدة الفول السوداني المقرمشة", "hs_code": "200811", "year": 2023,
    "market": {"iso3": ref.iso3, "m49": ref.m49, "iso2": ref.iso2,
              "name_en": ref.name_en, "name_ar": ref.name_ar},
    "markets": [],
    "deep_research": {
        "trace_id": "sample-client-qat-peanut",
        "missions": missions,
        "analyst": {
            "report": analyst_report,
            "by_category": {
                "demand": [missions["trade_flow"].findings[0]],
                "entry_cost": [agreements]},
            "missing_categories": [],
        },
        "verdict": {
            "verdict": "CONDITIONAL-GO",
            "ai": {"verdict": "CONDITIONAL-GO", "confidence": 0.62,
                  "reasoning": "الأدلة تدعم دخولاً مشروطاً بتأمين قنوات التوزيع."},
        },
        "report": {"report": REPORT_TEXT, "review_cycles": 2,
                  "unresolved_notes": []},
        "importer_leads": {"path": "scraper",
            "note": "عيّنة توضيحية",
            "leads": [
                {"name": "Five Group Trading Company", "address": "الدوحة (نموذج)",
                 "phone": "—", "email": "—", "website": "—", "rating": None,
                 "review_count": None, "maps_link": "—",
                 "doc_level": "○ مرشّح ويب غير موثَّق"}]},
    },
}


def qatar_research_blob() -> dict:
    """نسخةٌ طازجةٌ من النتيجة (لا حالةٌ مشتركةٌ بين الاختبارات)."""
    import copy
    return copy.deepcopy(result)

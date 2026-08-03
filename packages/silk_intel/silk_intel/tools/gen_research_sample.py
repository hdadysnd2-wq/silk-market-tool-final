"""يولّد samples/research_report_latest.docx من نتيجة /research مموّهة كاملة
(الموجة ٩، محدَّثة في الموجة ١١ — بوابة التسليم: "نموذج DOCX قابل للمراجعة
داخل الـPR نفسه"). لا شبكة — بيانات مموّهة موسومة المصدر مطابقة لبنية
نتيجة حقيقية (إسبانيا × تمور — نفس السوق الذي كشف تغطية "المنافسين"
الصفرية وأطلق تصليب الموجة ١١)، بالبنية العلمية الدولية بأحد عشر قسماً
(الموجة ١٠) وهوية سِلك البصرية (الموجة ١١).

Usage:  python3 tools/gen_research_sample.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_agents import AgentReport
from silk_data_layer import DataPoint
from silk_market_resolver import resolve_market
from silk_render import build_view
from silk_reports import render_docx, render_markdown

ref, _ = resolve_market("Spain")

REPORT_TEXT = """## 1. الخلاصة التنفيذية

التوصية CONDITIONAL-GO لثلاثة أسباب متضافرة: أولاً الشريحة المسلمة في إسبانيا نحو
2.1 مليون نسمة ضمن واردات تمور سنوية تبلغ 61 مليون دولار؛ وثانياً سوق
مورّدين مجزَّأ (HHI≈2350، لا مورّد مهيمناً) يفتح مجالاً حقيقياً لمورّد
جديد منافس بالسعر؛ وثالثاً نمو الواردات 9% مركّباً على ثلاث سنوات. تتحول
التوصية إلى GO أقوى متى تأكدت شهادة المنشأة المعتمدة EU 2017/625 خلال ٩٠
يوماً، ثم تعاقد المصدّر مع موزّع واحد على الأقل من الباب الأول أدناه خلال
المهلة نفسها. المخاطر الرئيسية الثلاث: بوابة الأهلية الأوروبية أولاً، ثم
تقلّب سعري محدود لليورو بين آخر سنتين، ثم منافسة تونس والمغرب بالسعر.

**ماذا يعني هذا لقرارك:** ابدأ تجهيز ملف الأهلية الأوروبية الآن — هو
البوابة الحرجة الوحيدة قبل أي خطوة تسويقية.

## 2. منهجية البحث ونطاقه

اعتمد هذا التقرير على Comtrade (تدفقات الاستيراد والمورّدون)، World
Bank (السكان والدخل ومؤشرات الحوكمة وسعر الصرف)، WITS (التعريفة)،
وبحث ويب موجَّه (الأسعار والمستوردون وثقافة الاستهلاك). ١٠ من ١٢
بعثة أنتجت أدلة مستشهَداً بها. سنة البيانات الأساسية 2023. تعريف
السوق: إسبانيا (ESP)، رمز HS080410 (تمور).

## 3. نظرة عامة على السوق وحجمه

واردات إسبانيا من تمور HS080410 بلغت 61 مليون دولار عام 2023 (UN
Comtrade)، بنمو 9% مركّباً على ثلاث سنوات. حساب TAM/SAM/SOM: TAM =
61,000,000$ (إجمالي واردات السوق). SAM = TAM × 3.4% (حصة الشريحة
الحلال المتخصصة المقدَّرة من نمط استهلاك الجاليات المسلمة) ≈
2,074,000$. SOM = SAM × 8% (حصة واقعية مستهدَفة في أول ثلاث سنوات
دخول، افتراض متحفظ لمورّد جديد) ≈ 166,000$ سنوياً.

## 4. ديناميكيات السوق

محرّكات: نمو سكاني للجالية المسلمة ونمو دخل للفرد. معوّقات: بوابة
الأهلية الأوروبية الإلزامية. فرص: تجزّؤ المورّدين (HHI≈2350) يترك
مجالاً لمنافس جديد. تهديدات: منافسة تونس والمغرب بأسعار أقل في نفس
القناة المتخصصة.

## 5. تحليل المستهلك والطلب

حساب صريح لحجم الشريحة: عدد سكان إسبانيا 47,500,000 × نسبة الشريحة
المسلمة المقدَّرة 4.4% ≈ 2,090,000 نسمة. بافتراض استهلاك موسمي 2
كغم/فرد سنوياً (نمط رمضان في أسواق أوروبية مشابهة) × متوسط سعر
تجزئة 9 يورو/كغم ≈ نطاق إيرادات محتمل يتراوح بين 3.3 و4.2 مليون
يورو سنوياً لكامل الشريحة. اتجاه بحث خمس سنوات صاعد بذروة موسمية
واضحة حول رمضان (Google Trends).

## 6. المشهد التنافسي

مؤشر تركّز المورّدين HHI≈2350 (نطاق معتدل — لا مورّد مهيمناً) من
comtrade_competitors:

| الدولة المورّدة | الحصة |
| --- | --- |
| تونس | 34% |
| الجزائر | 22% |
| المغرب | 18% |
| باقي المورّدين | 26% |

سلّم أسعار التجزئة المرصود:

| المنتج/العلامة | السعر | العملة | المصدر |
| --- | --- | --- | --- |
| تمور اقتصادية (سوبرماركت عام) | 5.80 | EUR/كغم | Mercadona (رصد ويب) |
| تمور متوسطة | 8.90 | EUR/كغم | Carrefour (رصد ويب) |
| تمور فاخرة (متجر متخصص) | 13.50 | EUR/كغم | رصد ويب متعدد |

حساب الهامش: سعر التصدير 9.1$/كغم + شحن 0.85$/كغم + تعريفة 0% =
تكلفة واصلة 9.95$/كغم ≈ 9.2 يورو/كغم — يقع عند حافة الطبقة المتوسطة/
الفاخرة، هامش موجب فقط عند استهداف القناة المتخصصة لا السوبرماركت
العام.

## 7. التنظيم والوصول للسوق

| الاشتراط | رقم اللائحة | الإجراء المطلوب |
| --- | --- | --- |
| تسجيل منشأة معتمدة | EU 2017/625 | تسجيل قبل أي شحنة — بوابة أهلية إلزامية |
| شهادة حلال | معيار GSO 993 | شهادة معتمدة من جهة مانحة معترف بها |

التعريفة الأوروبية على HS080410 صفر وفق نظام GSP+ للسعودية.

## 8. اللوجستيات وسلسلة الإمداد

ميناء فالنسيا أقرب بوابة استيراد رئيسية، مؤشر أداء اللوجستيات
الإسباني جيد نسبياً (World Bank LPI). أنواع القنوات المتاحة: موزّع
أغذية متخصص، سلاسل سوبرماركت إثنية، تجارة إلكترونية.

## 9. تقييم المخاطر

الاستقرار السياسي وسيادة القانون مستقران نسبياً (World Bank WGI).
تقلّب سعر الصرف محدود: اليورو/دولار تحرّك نحو 2% بين آخر سنتين
مرصودتين (World Bank PA.NUS.FCRF) — تقلّب منخفض نسبياً. لا أخبار
مخاطر قطاعية جوهرية خلال 12 شهراً (GDELT).

## 10. التوصيات الاستراتيجية

تدعم الأدلة دخولاً مشروطاً بتأمين الأهلية التنظيمية أولاً. أقوى ثلاثة
أسباب: أولاً شريحة مستهدَفة 2.09 مليون نسمة ضمن واردات السوق؛ وثانياً
سوق مورّدين مجزَّأ (HHI≈2350) يسمح بدخول منافس جديد؛ وثالثاً نمو واردات
9% مركّباً. الشرط اللازم لبقاء الحكم: تأكيد الأهلية التنظيمية.

| البند | القيمة |
| --- | --- |
| التوصية | دخول مشروط |
| درجة الثقة | متوسطة |

### خارطة طريق الدخول (٩٠ يوماً)

(أ) الشريحة المستهدَفة هي شريحة الطلب المحسوبة في تحليل المستهلك (نحو
2,090,000 نسمة). (ب) التموضع بين طبقة Carrefour المتوسطة (8.90€) وطبقة
الفاخر (13.50€) وفق سلّم الأسعار المرصود، بهامش تقديري 1.2-2.0 يورو/كغم
بعد تكلفة الهبوط 9.2€ عند القناة المتخصصة حصراً. (ج) الباب الأول: موزّعو أغذية حلال
متخصصون في مدريد وبرشلونة (○ غير متحقق، يتطلب تحققاً مباشراً). (د)
أول ثلاث خطوات: 1) تسجيل المنشأة كمعتمدة EU 2017/625 — مسؤول: فريق
الامتثال، تكلفة متوسطة؛ 2) عيّنة تجريبية لموزّع مرشّح — مسؤول: فريق
المبيعات، تكلفة منخفضة؛ 3) دراسة تسعير تنافسي مباشر مقابل تونس/
الجزائر — مسؤول: فريق التسويق، تكلفة منخفضة. (هـ) مؤشرا القلب:
تسجيل الأهلية خلال ٩٠ يوماً، ورد فعل سعري من موزّع واحد على الأقل.

**ماذا يعني هذا لقرارك:** هذه الخطوات الثلاث تحدد إن كانت التوصية
تتحول لـ GO كامل خلال ربع واحد أو تتجمّد.

## 11. الملاحق

أدلة التقاطعات الخمسة الكاملة (الطلب، تكلفة الدخول، التنافسية
السعرية، أبواب الدخول، SWOT) والملحق التقني الكامل (كل استشهاد برقم
ثقته الخام ومصدره وتاريخه) يليان آلياً أسفل هذا القسم.
"""


def _mkreport(name, findings, summary):
    return AgentReport(f"LLMAgent:{name}", findings, False, summary)


def _finding(value, source, confidence, note):
    return DataPoint(value, source, confidence, note, "2026-07-01")


demand_findings = [
    _finding("الشريحة المسلمة في إسبانيا نحو 2.09 مليون نسمة",
             "مرجع الديموغرافيا الداخلي (demographics_l1.csv)", 0.75,
             "[demand] تقدير 4.4% من 47.5 مليون نسمة"),
    _finding("واردات إسبانيا من تمور HS080410 بلغت 61 مليون دولار (2023)",
             "UN Comtrade", 0.9, "[demand] تدفق استيراد مباشر"),
    _finding("نمو الواردات 9% مركّباً على ثلاث سنوات",
             "UN Comtrade", 0.85, "[demand] اتجاه ثلاث سنوات"),
]
entry_cost_findings = [
    _finding("تعريفة صفرية على HS080410 ضمن GSP+", "WITS/WTO Tariff", 0.8,
             "[entry_cost] تعريفة مطبّقة"),
    _finding("تكلفة شحن بحري مقدَّرة 0.85$/كغم", "تقدير لوجستي داخلي", 0.5,
             "[entry_cost] تقدير غير رسمي"),
]
price_findings = [
    _finding("Mercadona: تمور اقتصادية 5.80€/كغم", "Mercadona (رصد ويب)",
             0.6, "[price_competitiveness] سعر تجزئة مرصود"),
    _finding("Carrefour: تمور متوسطة 8.90€/كغم", "Carrefour (رصد ويب)", 0.6,
             "[price_competitiveness] سعر تجزئة مرصود"),
    _finding("متاجر متخصصة: تمور فاخرة حتى 13.50€/كغم", "رصد ويب متعدد", 0.5,
             "[price_competitiveness] نطاق تقديري"),
]
entry_door_findings = [
    _finding("موزّع أغذية حلال في مدريد — مرشّح محتمل", "بحث ويب (غير مؤكَّد)",
             0.35, "[entry_door] مرشّح غير متحقق"),
]
swot_findings = [
    _finding("تعريفة صفرية وسوق مورّدين مجزَّأ (قوة)", "تحليل مركّب", 0.7,
             "[swot] نقطة قوة"),
    _finding("لا حضور علامة سعودية مثبت (ضعف)", "تحليل مركّب", 0.55,
             "[swot] نقطة ضعف"),
]

analyst_findings = (demand_findings + entry_cost_findings + price_findings
                    + entry_door_findings + swot_findings)
analyst_report = AgentReport("LLMAgent:market_analyst", analyst_findings,
                             False, "تحليل التقاطعات الخمسة مكتمل بأدلة كافية")

missions = {
    "trade_flow": _mkreport("trade_flow", [
        _finding(61_000_000.0, "UN Comtrade", 0.9, "واردات 2023")],
        "تدفقات تجارية مؤكَّدة من Comtrade"),
    "demand_trends": _mkreport("demand_trends", [
        _finding("اتجاه بحث 5 سنوات صاعد + ذروة موسمية رمضان",
                 "Google Trends", 0.6, "خمس سنوات + 12 شهراً + رمضان")],
        "اتجاه طلب موسمي واضح حول رمضان"),
    "pricing_scout": _mkreport("pricing_scout", price_findings,
                               "سلّم أسعار ثلاثي الطبقات مرصود"),
    "consumer_culture": _mkreport("consumer_culture", [
        _finding("التمور مرتبطة ثقافياً بموسم رمضان لدى الجالية المسلمة",
                 "OpenAlex + بحث ويب", 0.55, "استهلاك موسمي مرتبط دينياً")],
        "نمط استهلاك موسمي مرتبط برمضان"),
    "channels_importers": _mkreport("channels_importers", entry_door_findings,
                                    "موزّع محتمل واحد مرصود، يتطلب تحققاً"),
    "competitors": _mkreport("competitors", [
        _finding({"partner": "تونس", "code": "788", "value_usd": 20_740_000.0,
                 "share": 34.0}, "UN Comtrade", 0.9,
                 "[price_competitiveness] مورّد رئيسي — comtrade_competitors"),
        _finding({"partner": "الجزائر", "code": "012", "value_usd": 13_420_000.0,
                 "share": 22.0}, "UN Comtrade", 0.9,
                 "[price_competitiveness] مورّد رئيسي — comtrade_competitors"),
        _finding({"partner": "المغرب", "code": "504", "value_usd": 10_980_000.0,
                 "share": 18.0}, "UN Comtrade", 0.9,
                 "[price_competitiveness] مورّد — comtrade_competitors"),
        _finding({"year": 2023, "hhi": 2352.0, "supplier_count": 9},
                 "UN Comtrade", 0.9,
                 "مؤشر تركّز مورّدي إسبانيا 2023 — HHI=2352 (معتدل)")],
        "سوق مورّدين مجزَّأ — HHI معتدل، لا مورّد مهيمناً"),
    "risk_news": _mkreport("risk_news", [
        _finding("لا أخبار مخاطر جوهرية خلال 12 شهراً", "GDELT", 0.6,
                 "بلا حوادث مؤثرة"),
        _finding(0.92, "World Bank", 0.95, "PA.NUS.FCRF year=2023"),
        _finding(0.94, "World Bank", 0.95, "PA.NUS.FCRF year=2022"),
    ], "تقلّب عملة منخفض (٢٪)، لا مخاطر إخبارية جوهرية"),
    "demographics_economy": _mkreport("demographics_economy", [
        _finding(47_500_000.0, "World Bank", 0.95, "SP.POP.TOTL year=2023"),
        _finding(29_350.0, "World Bank", 0.95, "NY.GDP.PCAP.CD year=2023")],
        "مؤشرات اقتصادية مستقرة"),
    "customs_requirements": _mkreport("customs_requirements", [
        _finding("تسجيل منشأة معتمدة EU 2017/625 إلزامي", "EU 2017/625",
                 0.9, "بوابة أهلية إلزامية")], "اشتراط أهلية أوروبي واحد حرج"),
    "tariffs_agreements": _mkreport("tariffs_agreements", [
        _finding("تعريفة صفرية ضمن GSP+", "WITS/WTO Tariff", 0.8,
                 "تفضيل جمركي قائم")], "تعريفة صفرية مؤكَّدة"),
    "opportunity_gaps": _mkreport("opportunity_gaps", [], "لا فجوات إضافية مرصودة"),
    "logistics": _mkreport("logistics", [
        _finding("ميناء فالنسيا أقرب بوابة استيراد رئيسية", "مرجع الموانئ",
                 0.7, "بنية تحتية لوجستية ناضجة")], "بنية لوجستية ناضجة"),
}

result = {
    "product": "تمور", "hs_code": "080410", "year": 2023,
    "market": {"iso3": ref.iso3, "m49": ref.m49, "iso2": ref.iso2,
              "name_en": ref.name_en, "name_ar": ref.name_ar},
    "markets": [],
    "deep_research": {
        "trace_id": "sample-wave11-esp-dates",
        "missions": missions,
        "analyst": {
            "report": analyst_report,
            "by_category": {
                "demand": demand_findings,
                "entry_cost": entry_cost_findings,
                "price_competitiveness": price_findings,
                "entry_door": entry_door_findings,
                "swot": swot_findings,
            },
            "missing_categories": [],
        },
        "verdict": {
            # WP-1: الحكم المعروض من الحقل الحتمي حصراً — العيّنة تحاكي
            # تشغيلة النظام الجديد (الكاتب مقيَّد بالحكم الحتمي فيطابقه
            # جدول القرار في REPORT_TEXT: «| التوصية | دخول مشروط |»).
            "verdict": "CONDITIONAL-GO",
            "confidence": 0.64,
            "ai": {"verdict": "CONDITIONAL-GO", "confidence": 0.64,
                  "reasoning": ("الأدلة تدعم دخولاً مشروطاً بتأمين الأهلية "
                               "التنظيمية أولاً — تجزّؤ سوق المورّدين "
                               "(HHI معتدل) والفجوة السعرية كافيان، "
                               "والمخاطرة الرئيسية إجرائية لا سوقية.")},
        },
        "report": {"report": REPORT_TEXT, "review_cycles": 2,
                  "unresolved_notes": []},
        # C5 (Command #5b): قائمة مستوردين قابلين للتواصل — عيّنة مموّهة
        # موسومة المصدر (خرائط قوقل + مرشّح ويب) لعرض الجدول في النموذج.
        "importer_leads": {"path": "scraper",
            "note": "مرصود عبر مكشطة خرائط قوقل (هاتف/إيميل) — عيّنة توضيحية",
            "leads": [
                {"name": "Ejmar Import BV", "address": "Barcelona (نموذج)",
                 "phone": "+34 93 000 0000", "email": "info@ejmar.example",
                 "website": "ejmar.example", "rating": 4.4, "review_count": 76,
                 "maps_link": "https://maps.google/ejmar",
                 "doc_level": "◐ مرصود عبر خرائط قوقل"},
                {"name": "Halal Mayorista SL", "address": "Madrid (نموذج)",
                 "phone": "+34 91 000 0000", "email": "ventas@halalm.example",
                 "website": "halalm.example", "rating": 4.1, "review_count": 41,
                 "maps_link": "https://maps.google/halalm",
                 "doc_level": "◐ مرصود عبر خرائط قوقل"},
                {"name": "All4Trade (مرشّح ويب)", "address": "—", "phone": "—",
                 "email": "—", "website": "—", "rating": None,
                 "review_count": None, "maps_link": "—",
                 "doc_level": "○ مرشّح ويب غير موثَّق"}]},
    },
}

os.environ["SILK_HERMETIC"] = "1"
view = build_view(result)

# بوابة الجودة (الموجة ١٠) — تعمل هنا أيضاً كما في /research الفعلي، لتُظهر
# نتيجتها ضمن قسم "منهجية البحث ونطاقه" حتى في النموذج المرجعي.
import silk_quality_gate  # noqa: E402
gate_out = silk_quality_gate.run_quality_gate(view)
view["deep_research"]["quality_gate"] = gate_out

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out_path = os.path.join(_repo_root, "samples", "research_report_latest.docx")
render_docx(view, out_path)
print("wrote", out_path, "— quality gate:", gate_out["verdict"])

# تدقيق تصدير /research: report.md لنتيجة بحث عميق يُصيَّر من deep_research
# (silk_reports._md_deep_research) لا من قالب /analyze الفارغ — نُثبت المخرَج
# المُصلَح كعيّنة ملتزَمة (§10.6).
md_path = os.path.join(_repo_root, "samples", "research_report_latest.md")
with open(md_path, "w", encoding="utf-8") as _fh:
    _fh.write(render_markdown(view))
print("wrote", md_path)

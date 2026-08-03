"""المدوّنة القانونية الحقيقية الشكل — زبدة الفول السوداني × اليمن (Yemen blob).

> **حالة الإعادة الإنتاجية.** هذه صورة `/research` كما تُخزَّن فعلياً
> (`api._run_research_pipeline` → `silk_storage.save_analysis`) لتقرير زبدة
> الفول السوداني/اليمن الذي دقّقه المالك تحريرياً. تُجمِّد كل **عائلات العيوب**
> التي رصدها التدقيق كي تصير أقفال اختبار دائمة (أمر العمل الرئيس — ترقية محرّك
> جودة التقرير): رمز HS مُصنَّف خطأً (زبدة 040510 بدل عائلة الفول السوداني
> 200811/210690)، أرقام بنك دولي قديمة (2013/2018)، طلب Trends ضعيف على الصفة
> الدقيقة قوي على الفئة الأعمّ، صفوف أسعار بلا وزن، وHHI محسوب فوق رمز مُعلَّم.
>
> **One reproduction case.** The real stored shape of the audited Yemen
> peanut-butter `/research` result, freezing every editorial defect family so
> the engine fixes become permanent lock-tests. Same keys/shape as
> `tools/canonical_netherlands.py`; only the values carry the defects.

المكتبات: stdlib فقط (dicts خام) — يستورده الاختبار الهرمتي وبذر الخادم الحقيقي.
"""
from __future__ import annotations


def _dp(value, source: str = "UN Comtrade", conf: float = 0.8,
        note: str = "", ra: str = "2026-07-15", status: str = "",
        data_year=None) -> dict:
    """نقطة بيانات خام كما تُخزَّن (لا كائن DataPoint). A raw DataPoint dict.
    `data_year`: الحقل البنيويّ لسنة البيانات (الدرس ٣٣) — يضبطه الجامعون."""
    return {"value": value, "source": source, "confidence": conf,
            "note": note, "retrieved_at": ra, "status": status,
            "data_year": data_year}


# اسم المنتج ورمزه المُصنَّف خطأً — الصفة المميّزة «فول سوداني» ضاعت لصالح
# تطابق «زبدة» العاري (040510 = Butter)؛ العائلة الصحيحة 200811 (فول سوداني
# محضّر) أو 210690 (محضرات غذائية). هذه بذرة اختبار بوابة التأكيد المسبق (1.2).
YEMEN_PRODUCT = "زبدة الفول السوداني"
YEMEN_WRONG_HS = "040510"          # Butter / زبدة — تصنيف خاطئ (العيب)
YEMEN_RIGHT_HS_FAMILY = ("200811", "210690")


# السرد الحقيقي — بنية الكاتب الأحد عشر قسماً، بأرقام مبنيّة على الرمز المُعلَّم
# (كلها «مؤشر سياقي» لا مقياس فعلي) + أرقام بنك دولي قديمة + طلب Trends ضعيف.
REPORT_TEXT = """## 1. الخلاصة التنفيذية
الحكم WATCH بدرجة ثقة 0.55. واردات اليمن من الزبدة (رمز 040510) نحو 12 مليون
دولار، والمشهد مركّز (HHI 3100). دخل الفرد 1106 دولار.

## 2. منهجية البحث ونطاقه
اثنتا عشرة بعثة بحث، ثم محلّل شامل فكاتب التقرير. رمز HS المستخدم 040510،
بينما العائلة الأدقّ لهذا المنتج هي البند 2008 (محضرات الفول السوداني) — انظر
الملاحظة المنهجية.

## 3. نظرة عامة على السوق وحجمه
واردات 2023 نحو 12 مليون دولار وفق UN Comtrade تحت الرمز 040510.

## 4. ديناميكيات السوق
نمو سنوي مركّب (CAGR) 6% على مدى ثلاث سنوات.

## 5. تحليل المستهلك والطلب
دخل الفرد 1106 دولار (2013) ونسبة الفقر 31.5% (2018). الطلب على «زبدة الفول
السوداني» ضعيف (0.4 من 100) بينما «فوائد زبدة الفول السوداني» يبلغ 100. لا
بيانات موسمية/رمضانية من Trends.

## 6. المشهد التنافسي
مورّدون: مصر، الهند، الإمارات. مؤشر التركّز HHI = 3100 (سوق مركّز جداً).
أسعار الرفّ المرصودة بلا وزن مذكور في بعض الصفوف.

## 7. التنظيم والوصول للسوق
اشتراطات استيراد عامة؛ لا لائحة مرقّمة مرصودة.

## 8. اللوجستيات وسلسلة الإمداد
شحن بحري عبر ميناء عدن.

## 9. تقييم المخاطر
استقرار سياسي منخفض؛ تقلّب سعر الصرف حاد.

## 10. التوصيات الاستراتيجية
ينبغي التعامل مع أرقام الاستيراد كمؤشر سياقي لا كمقياس مباشر حتى تأكيد الرمز.
### خارطة طريق الدخول (٩٠ يوماً)
1. الحصول على بيانات استيراد تحت الرمز الصحيح. 2. تعاقد مع موزّع محلي مؤكَّد.

## 11. الملاحق
UN Comtrade, World Bank, Google Maps."""


def yemen_research_blob() -> dict:
    """المدوّنة كما تُخزَّن وتُقرَأ (dicts خام) — نفس شكل هولندا تماماً، بقيم
    تحمل عائلات العيوب. تعيد dict جديدة كل نداء (المتّصل يبذر صفّ DB متغيّراً)."""
    def _m(summary, findings=None, failed=False):
        return {"agent_name": "LLMMissionAgent", "summary": summary,
                "findings": findings or [], "failed": failed}
    missions = {
        # واردات محسوبة تحت الرمز الخاطئ 040510 (زبدة) — «مؤشر سياقي».
        "trade_flow": _m("واردات الزبدة (040510) نحو 12 مليون دولار (70/70 بند)",
                         [_dp(12_000_000, note="واردات 2023 تحت الرمز 040510")]),
        # صفوف أسعار: بعضها بلا وزن مذكور => لا سعر/كجم يُحسب (عيب 3.1).
        "pricing_scout": _m("أسعار رفّ مرصودة، بعضها بلا وزن",
                            [_dp("علبة 5 دولار", "Google Maps",
                                 note="وزن غير مذكور", conf=0.4),
                             _dp("6.5 دولار/كجم", "Google Maps",
                                 note="Carrefour Aden")]),
        "competition": _m("HHI 3100 — سوق مركّز (تحت الرمز 040510)",
                          [_dp(3100, note="HHI محسوب من حصص الرمز 040510")]),
        # طلب Trends: الصفة الدقيقة ضعيفة، الفئة الأعمّ قوية (عيب 2.3)؛
        # ولا سلسلة موسمية (عيب 2.2).
        "demand_trends": _m("طلب الصفة الدقيقة ضعيف؛ الفئة أقوى",
                            [_dp(0.4, "Google Trends",
                                 note="زبدة الفول السوداني — الصفة الدقيقة"),
                             _dp(100, "Google Trends",
                                 note="فوائد زبدة الفول السوداني — الفئة الأعمّ"),
                             _dp(None, "Google Trends", conf=0.0,
                                 note="no series for seasonality of "
                                      "'رمضان زبدة الفول السوداني'",
                                 status="fetch_failed")]),
        # دخل بنك دولي قديم — 2013 و2018 (عيب 2.1).
        "economic": _m("دخل الفرد 1106 دولار (2013)",
                       [_dp(1106, "World Bank", note="دخل الفرد (2013)",
                            ra="2026-07-15", data_year=2013),
                        _dp(31.5, "World Bank", note="نسبة الفقر (2018)",
                            ra="2026-07-15", data_year=2018)]),
        "risk_news": _m("استقرار سياسي منخفض", []),
    }
    analyst = {
        "report": {"agent_name": "market_analyst",
                   "summary": "اليمن WATCH — الرمز المُصنَّف خطأً يُضعِف اليقين.",
                   "findings": [], "failed": False},
        "missing_categories": [],
        "by_category": {
            "demand": [_dp(12_000_000, note="واردات تحت الرمز 040510")],
            "price_competitiveness": [_dp("6.5 دولار/كجم", "Google Maps",
                                          note="Carrefour Aden")],
        },
    }
    # الحكم WATCH — يجب أن تُسقَف ثقته عند تعليم الرمز (1.3).
    verdict = {"verdict": "WATCH", "confidence": 0.55,
               "ai": {"verdict": "WATCH",
                      "reasoning": "سوق يحتاج بيانات تحت الرمز الصحيح وموزّعاً "
                                   "مؤكَّداً قبل الالتزام."}}
    report_out = {"report": REPORT_TEXT, "review_cycles": 1,
                  "unresolved_notes": [], "failure_reason": ""}
    return {
        "product": YEMEN_PRODUCT, "hs_code": YEMEN_WRONG_HS, "year": None,
        "preliminary": True,
        # علامة عدم تطابق الرمز — العقد الذي تستهلكه طبقة العرض والكاتب (1.3).
        # confirmed=False لأن صفة المنتج المميّزة «فول سوداني» غائبة عن وصف
        # الرمز 040510 (زبدة/Butter).
        "hs_confirmation": {
            "confirmed": False,
            "hs_code": YEMEN_WRONG_HS,
            "code_desc": "زبدة (Butter)",
            "product_terms": ["فول", "سوداني", "زبدة"],
            "shared_terms": ["زبدة"],
            "missing_terms": ["فول", "سوداني"],
            "reason": "وصف الرمز لا يشمل الصفة المميّزة «فول سوداني»",
        },
        "market": {"iso3": "YEM", "m49": 887, "iso2": "YE",
                   "name_en": "Yemen", "name_ar": "اليمن"},
        "markets": [],
        "deep_research": {"missions": missions, "analyst": analyst,
                          "verdict": verdict, "report": report_out,
                          "trace_id": "yem-real",
                          "budget_status": {"tail_degraded": False}},
        "data_economics": {"llm_calls": 28, "note": "28 نداء كلود"},
    }


if __name__ == "__main__":  # فحص يدوي سريع — طباعة مفاتيح المدوّنة القانونية
    import json
    blob = yemen_research_blob()
    print(json.dumps({k: (list(v.keys()) if isinstance(v, dict) else v)
                      for k, v in blob.items()},
                     ensure_ascii=False, indent=2))

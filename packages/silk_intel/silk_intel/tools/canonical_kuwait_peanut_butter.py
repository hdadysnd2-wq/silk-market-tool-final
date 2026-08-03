"""المدوّنة القانونية الحقيقية الشكل — زبدة الفول السوداني × الكويت (Kuwait blob).

> **حالة الإعادة الإنتاجية.** صورة `/research` كما تُخزَّن فعلياً، مُعاد
> بناؤها من تدقيق تقرير الكويت الحيّ (2026-07-21، أمر التثبيت). تُجمِّد ثلاث
> عائلات عيوبٍ حيّة معاً في مدوّنةٍ واحدة — نفس عائلة `tools/canonical_yemen.py`
> (زبدة الفول السوداني/اليمن) لكن **بسوقٍ مختلف تماماً وبلا أيّ سلسلة يمنية
> فيها إطلاقاً** — كي يصلح هذا الملف بذرةً لاختبار «صفر تسرّب عبر-سوقي» بلا
> اعتماد دائري على مدوّنة اليمن نفسها:
>
>   ١) رمز HS مُصنَّف خطأً (زبدة 040510 بدل عائلة الفول السوداني 200811/210690).
>   ٢) تناقض سعرٍ حقيقي (تجزئة 0.67$/كجم من رصدٍ حقيقي < استيراد/جملة كومتريد
>      ~6$/كجم محسوب تحت الرمز الخاطئ) — البند 1.3 من أمر التثبيت.
>   ٣) لا أثر يمنيّ إطلاقاً (لا «اليمن»/«عدن»/«ربوع»/YEM) — بذرة اختبار
>      تسرّب السوق (LESSONS ٣٦).
>
> **One reproduction case.** Same shape/keys as `tools/canonical_netherlands.py`
> and `tools/canonical_yemen.py`; Kuwait-specific values, zero Yemen strings.

المكتبات: stdlib فقط (dicts خام) — يستورده الاختبار الهرمتي وبذر الخادم الحقيقي.
"""
from __future__ import annotations


def _dp(value, source: str = "UN Comtrade", conf: float = 0.8,
        note: str = "", ra: str = "2026-07-20", status: str = "",
        data_year=None) -> dict:
    """نقطة بيانات خام كما تُخزَّن (لا كائن DataPoint)."""
    return {"value": value, "source": source, "confidence": conf,
            "note": note, "retrieved_at": ra, "status": status,
            "data_year": data_year}


KUWAIT_PRODUCT = "زبدة الفول السوداني"
KUWAIT_WRONG_HS = "040510"          # Butter / زبدة — تصنيف خاطئ (نفس عيب اليمن)
KUWAIT_RIGHT_HS_FAMILY = ("200811", "210690")

# السرد الحقيقي — نفس بنية الكاتب الأحد عشر قسماً؛ أرقام بالكويت + تناقض
# السعر المحدَّد في أمر التثبيت (1.3) مذكور صراحة كي يمرّ عبر إعادة التأطير.
REPORT_TEXT = """## 1. الخلاصة التنفيذية
الحكم WATCH بدرجة ثقة 0.5. واردات الكويت من الزبدة (رمز 040510) نحو 9 مليون
دولار، والمشهد مركّز (HHI 2900).

## 2. منهجية البحث ونطاقه
اثنتا عشرة بعثة بحث، ثم محلّل شامل فكاتب التقرير. رمز HS المستخدم 040510،
بينما العائلة الأدقّ لهذا المنتج هي البند 2008 (محضرات الفول السوداني) — انظر
الملاحظة المنهجية.

## 3. نظرة عامة على السوق وحجمه
واردات 2023 نحو 9 مليون دولار وفق UN Comtrade تحت الرمز 040510.

## 4. ديناميكيات السوق
نمو سنوي مركّب (CAGR) 5% على مدى ثلاث سنوات.

## 5. تحليل المستهلك والطلب
دخل الفرد مرتفع نسبياً في الكويت. الطلب على «زبدة الفول السوداني» محدود
البيانات من Trends.

## 6. المشهد التنافسي
مورّدون: الإمارات، مصر، تركيا. مؤشر التركّز HHI = 2900 (سوق مركّز).
متوسط سعر الاستيراد الرسمي (UN Comtrade) نحو 6 دولار/كجم — مؤشر سياقي لفئة
مجاورة، بينما رُصد سعر تجزئة فعلي نحو 0.67 دولار/كجم لمنتج مشابه في السوق
المحلي؛ التناقض متوقَّع لكون رقم الاستيراد محسوباً لفئة كومتريد مجاورة لا
لهذا المنتج تحديداً — لا يُصلَح برقمٍ مختلَق.

## 7. التنظيم والوصول للسوق
اشتراطات استيراد خليجية عامة؛ لا لائحة مرقّمة مرصودة لهذا الرمز تحديداً.

## 8. اللوجستيات وسلسلة الإمداد
شحن بحري عبر ميناء الشويخ.

## 9. تقييم المخاطر
استقرار سياسي مرتفع نسبياً؛ مخاطر تركّز الموردين معلَّمة بسبب الرمز.

## 10. التوصيات الاستراتيجية
ينبغي التعامل مع أرقام الاستيراد كمؤشر سياقي لا كمقياس مباشر حتى تأكيد الرمز.
### خارطة طريق الدخول (٩٠ يوماً)
1. الحصول على بيانات استيراد تحت الرمز الصحيح. 2. تعاقد مع موزّع محلي مؤكَّد.

## 11. الملاحق
UN Comtrade, World Bank, Google Maps."""


def kuwait_research_blob() -> dict:
    """المدوّنة كما تُخزَّن وتُقرَأ (dicts خام) — نفس شكل هولندا/اليمن، بقيم
    الكويت. تعيد dict جديدة كل نداء (المتّصل يبذر صفّ DB متغيّراً)."""
    def _m(summary, findings=None, failed=False):
        return {"agent_name": "LLMMissionAgent", "summary": summary,
                "findings": findings or [], "failed": failed}
    missions = {
        "trade_flow": _m("واردات الزبدة (040510) نحو 9 مليون دولار",
                         [_dp(9_000_000, note="واردات 2023 تحت الرمز 040510")]),
        # صفّ الاستيراد/الجملة (كومتريد، تحت الرمز الخاطئ) + صفّ تجزئة حقيقي
        # مرصود — التناقض الدقيق المذكور في تدقيق البند 1.3.
        "pricing_scout": _m("سلّم أسعار: استيراد/جملة كومتريد + تجزئة مرصودة",
                            [_dp("~6 دولار/كجم", "UN Comtrade",
                                 note="متوسط سعر الاستيراد الرسمي (UN Comtrade، "
                                      "متوسط عبر مزيج الشحنات) — تحت الرمز 040510"),
                             _dp("0.67 دولار/كجم", "Google Maps",
                                 note="سعر تجزئة مرصود فعلياً — منتج مشابه محلي")]),
        "competition": _m("HHI 2900 — سوق مركّز (تحت الرمز 040510)",
                          [_dp(2900, note="HHI محسوب من حصص الرمز 040510")]),
        "demand_trends": _m("بيانات طلب محدودة", [
            _dp(None, "Google Trends", conf=0.0,
               note="no series for seasonality", status="fetch_failed")]),
        "economic": _m("دخل فرد مرتفع نسبياً (2021)",
                       [_dp(35000, "World Bank", note="دخل الفرد (2021)",
                            ra="2026-07-20", data_year=2021)]),
        "risk_news": _m("استقرار سياسي مرتفع نسبياً", []),
    }
    analyst = {
        "report": {"agent_name": "market_analyst",
                   "summary": "الكويت WATCH — الرمز المُصنَّف خطأً يُضعِف اليقين.",
                   "findings": [], "failed": False},
        "missing_categories": [],
        "by_category": {
            "demand": [_dp(9_000_000, note="واردات تحت الرمز 040510")],
            "price_competitiveness": [_dp("0.67 دولار/كجم", "Google Maps",
                                          note="سعر تجزئة مرصود")],
        },
    }
    verdict = {"verdict": "WATCH", "confidence": 0.5,
               "ai": {"verdict": "WATCH",
                      "reasoning": "سوق يحتاج بيانات تحت الرمز الصحيح وموزّعاً "
                                   "مؤكَّداً قبل الالتزام."}}
    report_out = {"report": REPORT_TEXT, "review_cycles": 1,
                  "unresolved_notes": [], "failure_reason": ""}
    return {
        "product": KUWAIT_PRODUCT, "hs_code": KUWAIT_WRONG_HS, "year": None,
        "preliminary": True,
        "hs_confirmation": {
            "confirmed": False,
            "hs_code": KUWAIT_WRONG_HS,
            "code_desc": "زبدة (Butter)",
            "product_terms": ["فول", "سوداني", "زبدة"],
            "shared_terms": ["زبدة"],
            "missing_terms": ["فول", "سوداني"],
            "reason": "وصف الرمز لا يشمل الصفة المميّزة «فول سوداني»",
        },
        "market": {"iso3": "KWT", "m49": 414, "iso2": "KW",
                   "name_en": "Kuwait", "name_ar": "الكويت"},
        "markets": [],
        "deep_research": {"missions": missions, "analyst": analyst,
                          "verdict": verdict, "report": report_out,
                          "trace_id": "kwt-real",
                          "budget_status": {"tail_degraded": False}},
        "data_economics": {"llm_calls": 26, "note": "26 نداء كلود"},
    }


if __name__ == "__main__":  # فحص يدوي سريع — طباعة مفاتيح المدوّنة القانونية
    import json
    blob = kuwait_research_blob()
    print(json.dumps({k: (list(v.keys()) if isinstance(v, dict) else v)
                      for k, v in blob.items()},
                     ensure_ascii=False, indent=2))

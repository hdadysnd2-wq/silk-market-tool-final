"""المدوّنة القانونية الحقيقية الشكل — تمور × هولندا (the canonical real-shape blob).

> **مصدر واحد.** هذا هو الشكل المرجعي الوحيد لنتيجة `/research` كما تُخزَّن
> فعلياً (`api._run_research_pipeline` → `silk_storage.save_analysis`). كل رُتب
> الاختبار (الهرمتية، الخادم الحقيقي رُتبة ٢، المتصفّح الحقيقي رُتبة ٣) تبذر
> منها كي تُختبر السلوك على **شكل الإنتاج**، لا على نموذج مثالي مبسّط.
>
> **One source.** The single reference shape of a `/research` result as it is
> actually persisted. Every test rung (hermetic, rung-2 real server, rung-3
> real browser) seeds from THIS builder so behaviour is exercised against the
> production shape, never an idealized toy.

البلاغ الأصلي (البند ٢ في `docs/LESSONS.md`): المُصدِّرات قرأت فرع `/analyze`
القديم بدل `deep_research`، فخرج تقرير بحث عميق بقالب فارغ. أقفال التصدير تعمل
على **شكل مدوّنة هولندا الحقيقي المُعاد بناؤه**، لا نماذج مثالية — وهذا الملف
يمركزها كي لا تتشعّب النسخ.

المكتبات: stdlib فقط (dicts خام). لا تبعيات — يستورده الاختبار الهرمتي وسكربت
بذر الخادم الحقيقي على حدٍّ سواء.
"""
from __future__ import annotations


def _dp(value, source: str = "UN Comtrade", conf: float = 0.8,
        note: str = "", ra: str = "2026-07-15") -> dict:
    """نقطة بيانات خام كما تُخزَّن (لا كائن DataPoint) — value/source/confidence/
    note/retrieved_at. A raw DataPoint dict exactly as persisted."""
    return {"value": value, "source": source, "confidence": conf,
            "note": note, "retrieved_at": ra}


# السرد الحقيقي — بنية الكاتب الأحد عشر قسماً (silk_ai_judge._REPORT_SECTIONS)
# مع لغة حكم مُعرَّبة ("confidence"→«درجة الثقة» عبر _strip_internal_plumbing)
# التي أسقطت تصدير العميل بـ501، وأرقام غنيّة (HHI، أسعار رفّ، لوائح EU).
REPORT_TEXT = """## 1. الخلاصة التنفيذية
الحكم WATCH بدرجة ثقة 0.6 (confidence). واردات هولندا من التمور تنمو 8% سنوياً،
والمشهد تنافسي مفتّت (HHI 940). أسعار الرفّ 6.20–9.80 يورو/كغم.

## 2. منهجية البحث ونطاقه
اثنتا عشرة بعثة بحث، جميعها ناجحة، ثم محلّل شامل فكاتب التقرير بدورتَي مراجعة.

## 3. نظرة عامة على السوق وحجمه
واردات 2023 نحو 42 مليون دولار.

## 4. ديناميكيات السوق
نمو مطّرد مدفوع بالطلب على المنتجات الصحية.

## 5. تحليل المستهلك والطلب
شريحتان: تجزئة راقية وجاليات.

## 6. المشهد التنافسي
مورّدون: تونس، الجزائر، إيران. مؤشر التركّز HHI = 940 (سوق مفتّت).

## 7. التنظيم والوصول للسوق
EU 2017/625 (منشأة معتمدة إلزامية)، EU 1169/2011 (وسم المستهلك).

## 8. اللوجستيات وسلسلة الإمداد
شحن بحري عبر ميناء روتردام.

## 9. تقييم المخاطر
تقلّب أسعار المنافسين؛ لا مخاطر تنظيمية حادة.

## 10. التوصيات الاستراتيجية
ابدأ باختبار السوق قبل الالتزام الكامل.
### خارطة طريق الدخول
1. تحقّق من المستوردين. 2. سجّل المنشأة لدى الجهة المختصة.

## 11. الملاحق
UN Comtrade, World Bank, Google Maps."""


def netherlands_research_blob() -> dict:
    """المدوّنة كما تُخزَّن وتُقرَأ (dicts خام، لا كائنات AgentReport) — الشكل
    الدقيق من `api._run_research_pipeline`: markets:[]، deep_research{missions,
    analyst,verdict,report,trace_id,budget_status}، market{iso3,m49,iso2,
    name_en,name_ar}، data_economics.

    The canonical stored blob for دات × هولندا. Return a FRESH dict each call
    (callers seed a mutable DB row from it)."""
    def _m(summary, findings=None, failed=False):
        return {"agent_name": "LLMMissionAgent", "summary": summary,
                "findings": findings or [], "failed": failed}
    missions = {
        "trade_flow": _m("واردات تنمو 8% (76/76 بند)",
                         [_dp(42_000_000, note="واردات 2023")]),
        "pricing_scout": _m("أسعار رفّ 6.20–9.80€ (60/60)",
                            [_dp(7.49, "Google Maps", note="Albert Heijn")]),
        "competition": _m("HHI 940 — سوق مفتّت", [_dp(940, note="HHI")]),
        "risk_news": _m("لا مخاطر حادة", []),
    }
    analyst = {
        "report": {"agent_name": "market_analyst",
                   "summary": "هولندا WATCH — سوق مفتّت بأسعار رفّ جيدة.",
                   "findings": [], "failed": False},
        "missing_categories": [],
        "by_category": {
            "demand": [_dp(42_000_000, note="واردات تنمو 8%")],
            "price_competitiveness": [_dp(7.49, "Google Maps",
                                          note="سعر رفّ")],
        },
    }
    verdict = {"verdict": "WATCH", "confidence": 0.6,
               "ai": {"verdict": "WATCH",
                      "reasoning": "سوق واعد لكن يحتاج تحقّق المستوردين."}}
    report_out = {"report": REPORT_TEXT, "review_cycles": 2,
                  "unresolved_notes": [], "failure_reason": ""}
    return {
        "product": "تمور", "hs_code": "080410", "year": None,
        "preliminary": True,
        "market": {"iso3": "NLD", "m49": 528, "iso2": "NL",
                   "name_en": "Netherlands", "name_ar": "هولندا"},
        "markets": [],
        "deep_research": {"missions": missions, "analyst": analyst,
                          "verdict": verdict, "report": report_out,
                          "trace_id": "nld-real",
                          "budget_status": {"tail_degraded": False}},
        "data_economics": {"llm_calls": 30, "note": "30 نداء كلود"},
    }


if __name__ == "__main__":  # فحص يدوي سريع — طباعة مفاتيح المدوّنة القانونية
    import json
    blob = netherlands_research_blob()
    print(json.dumps({k: (list(v.keys()) if isinstance(v, dict) else v)
                      for k, v in blob.items()},
                     ensure_ascii=False, indent=2))

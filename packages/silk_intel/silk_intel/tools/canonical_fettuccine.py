"""المدوّنة القانونية الحقيقية الشكل — فيتوتشيني × إيطاليا (Wave 2).

نظير `canonical_netherlands` لكنه **يُعيد إنتاج عيوب أوّل PDF حيّ** كي تُقفل
عليها اختبارات Wave 2 على شكلٍ حقيقيّ لا نموذجٍ مثالي:

- **رائدٌ بجغرافيا خاطئة** (البند ٤): عنوانٌ في الولايات المتحدة بينما السوق
  المدروسة إيطاليا => يُسقَط (فجوة معلنة).
- **رائدٌ من تسرّب نثر** (البند ٥): «اسمٌ» هو جملةُ بعثةٍ إنجليزية خام => يُسقَط
  (يُوجَّه للسرد؛ لا نثرٌ إنجليزيٌّ في خلية عميل).
- **رائدٌ حشو** (البند ٦): اسمٌ وكلُّ حقول الاتصال «—» => يُسقَط.
- **رائدٌ صالح** (إيطاليا، هاتف): يبقى — كي تُثبِت الفلترةُ أنها لا تُفرِط.
- **سطر إخلاء المسؤولية** (البند ١٠): يُشتَقّ من المنتج المدروس («فيتوتشيني»)
  لا «التمور السعودية» المثبَّتة.
- **العلامة «سِلك»** (البند ٨): من هوية العرض وقت التصدير (لا حقلَ في المدوّنة).

كل ذلك بشكل `api._run_research_pipeline`: markets:[]، deep_research بمفاتيحه،
importer_leads داخل deep_research، market{iso3,m49,iso2,name_en,name_ar}.
يُعيد dict طازجًا كل نداء (المستدعون يبذرون منه صفًّا قابلًا للتعديل).
"""
from __future__ import annotations


def _dp(value, source: str = "UN Comtrade", conf: float = 0.8,
        note: str = "", ra: str = "2026-07-18") -> dict:
    return {"value": value, "source": source, "confidence": conf,
            "note": note, "retrieved_at": ra}


# سردٌ حقيقيّ الشكل (١١ قسمًا) لمنتجٍ غير التمور — يُثبِت خلوّ القوالب من ترميز
# منتجٍ مثبَّت (لا «التمور السعودية» في تقرير معكرونة).
REPORT_TEXT = """## 1. الخلاصة التنفيذية
الحكم WATCH بدرجة ثقة 0.55 (confidence). إيطاليا من أكبر منتجي المعكرونة عالميًا،
فالدخول تنافسيّ جدًّا. أسعار الرفّ 1.10–2.40 يورو/كغم.

## 2. منهجية البحث ونطاقه
اثنتا عشرة بعثة بحث، ثم محلّل شامل فكاتب التقرير بدورتَي مراجعة.

## 3. نظرة عامة على السوق وحجمه
واردات 2023 نحو 30 مليون دولار (مع إنتاجٍ محلّيٍّ ضخم).

## 4. ديناميكيات السوق
سوقٌ ناضجة بمنتِجين محلّيين أقوياء.

## 5. تحليل المستهلك والطلب
تفضيلٌ قويّ للعلامات المحلّية.

## 6. المشهد التنافسي
منتِجون محلّيون مهيمنون؛ مؤشر التركّز HHI = 610.

## 7. التنظيم والوصول للسوق
EU 1169/2011 (وسم المستهلك)، اشتراطات المنشأ.

## 8. اللوجستيات وسلسلة الإمداد
شحن بحري عبر ميناء جنوة.

## 9. تقييم المخاطر
منافسةٌ محلّية حادّة؛ هامشٌ ضيّق.

## 10. التوصيات الاستراتيجية
راقب السوق؛ الدخول المباشر غير مُوصًى به حاليًا.

## 11. الملاحق
UN Comtrade, World Bank, Google Maps."""


def _leads_block() -> dict:
    """روابط تُعيد إنتاج البنود ٤/٥/٦ + رائدٍ صالحٍ يبقى."""
    def _lead(name, address="", phone="", email="", website="",
              rating=None, rc=None, maps="", doc="◐ مرصود عبر خرائط قوقل",
              src="google_maps_scraper"):
        return {"name": name, "address": address, "phone": phone,
                "email": email, "website": website, "rating": rating,
                "review_count": rc, "maps_link": maps, "doc_level": doc,
                "source": src}
    return {
        "path": "scraper",
        "note": "خرائط قوقل + مرشّحو ويب",
        "leads": [
            # صالح (إيطاليا، هاتف) — يبقى بعد الفلترة.
            _lead("Pastificio Milano Srl", "Via Roma 12, Milano, Italy",
                  phone="+39 02 1234567", rating=4.5, rc=88,
                  maps="https://maps.google.com/?q=pastificio"),
            # جغرافيا خاطئة (البند ٤): عنوانٌ في الولايات المتحدة — يُسقَط.
            _lead("NutsWorld Trading Inc",
                  "500 Market St, San Francisco, United States",
                  phone="+1 415 000 0000", rating=4.1, rc=40),
            # تسرّب نثر (البند ٥): «اسمٌ» هو جملةٌ إنجليزية خام — يُسقَط.
            _lead("Italy imports a significant volume of pasta from several "
                  "European suppliers according to recent trade data.",
                  doc="○ مرشّح ويب غير موثَّق", src="web_search"),
            # حشو (البند ٦): اسمٌ وكلُّ الاتصال فارغ — يُسقَط.
            _lead("Anonimo Distribuzione"),
        ],
    }


def fettuccine_research_blob() -> dict:
    def _m(summary, findings=None, failed=False):
        return {"agent_name": "LLMMissionAgent", "summary": summary,
                "findings": findings or [], "failed": failed}
    missions = {
        "trade_flow": _m("واردات 30م$ (سوق ناضجة)",
                         [_dp(30_000_000, note="واردات 2023")]),
        "competition": _m("HHI 610 — منتِجون محلّيون", [_dp(610, note="HHI")]),
        "channels_importers": _m("مرشّحون",
                                 [_dp("Pastificio Milano Srl", "Web",
                                      note="مرشّح")]),
    }
    analyst = {
        "report": {"agent_name": "market_analyst",
                   "summary": "إيطاليا WATCH — منتِجون محلّيون أقوياء.",
                   "findings": [], "failed": False},
        "missing_categories": [],
        "by_category": {"demand": [_dp(30_000_000, note="واردات")]},
    }
    verdict = {"verdict": "WATCH", "confidence": 0.55,
               "ai": {"verdict": "WATCH",
                      "reasoning": "سوقٌ ناضجةٌ بمنافسةٍ محلّية حادّة."}}
    report_out = {"report": REPORT_TEXT, "review_cycles": 2,
                  "unresolved_notes": [], "failure_reason": ""}
    return {
        "product": "معكرونة فيتوتشيني", "hs_code": "190219", "year": None,
        "preliminary": True,
        "market": {"iso3": "ITA", "m49": 380, "iso2": "IT",
                   "name_en": "Italy", "name_ar": "إيطاليا"},
        "markets": [],
        "deep_research": {"missions": missions, "analyst": analyst,
                          "verdict": verdict, "report": report_out,
                          "trace_id": "ita-fettuccine",
                          "importer_leads": _leads_block(),
                          "budget_status": {"tail_degraded": False}},
        "data_economics": {"llm_calls": 28, "note": "28 نداء كلود"},
    }

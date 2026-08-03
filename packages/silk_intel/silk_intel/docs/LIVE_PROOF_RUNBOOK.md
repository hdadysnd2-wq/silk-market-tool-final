# دليل الإثبات الحيّ — Live-proof runbook

> **الغرض.** إجراء واحد قابل للنسخ يُنتِج أول إثبات حيّ حقيقي لمسار `/research`
> على نشرٍ حقيقي بمفاتيح حقيقية: تشغيلة تمور × هولندا، ثم إعادة توليد التقرير
> الرخيصة (نداء كاتب واحد بدل إعادة البحث كله)، ثم التقاط أول عيّنة حقيقية وأول
> حالة ذهبية. كل الأرقام تُسحب من مصادر رسمية حيّة — **لا اختلاق، لا رقم من كلود
> يُعامَل كمرجع** (المبدأ التأسيسي، `CLAUDE.md`).
>
> **Purpose.** One copy-pasteable procedure that produces the first real live
> proof of `/research` on a real deployment: dates × Netherlands, then the cheap
> report-regeneration path, then capturing the first real sample + first golden
> case. Every number is pulled from an official live source — never fabricated,
> never a Claude number treated as a reference.

هذا الدليل يُشغَّل على نشرٍ حقيقي (Railway مثلاً) بمفاتيح حقيقية في البيئة —
لا يُشغَّل هيرمتياً. الاختبارات الهيرمتية تثبت *العقود* (تدهور رشيق، تطهير،
حدود الميزانية)؛ هذا الدليل يثبت أن المسار الحيّ يُنتِج تقريراً فعلاً.

> **رُتب الاختبار قبل المالك (المالك آخِر تأكيد لا أوّل مكتشف — البند ١٥ في
> `docs/LESSONS.md`).** قبل أن يرى المالك أيّ تغيير يمسّ سلوكاً إنتاجياً،
> تُستنفد الرُتب محلياً/على CI: **(١) هرمتي** `pytest tests/ -q`؛ **(٢) خادم
> حقيقي** — `SILK_RUN_E2E=1 pytest tests/test_rung2_real_server.py` يُقلِع
> `uvicorn api:app` على SQLite مبذور بالمدوّنة القانونية الحقيقية الشكل
> (`tools/canonical_netherlands.py` / `tools/live_shape_server.py`) ويضرب كل
> نقطة نهاية بـHTTP حقيقي؛ **(٣) متصفّح حقيقي** —
> `tests/test_rung3_playwright_e2e.py` يشغّل chromium (headless) لينقر الواجهة
> الفعلية (شريط جانبي ← تقرير ← تصدير Word/Markdown ← صندوق تقدّم)؛ **(٤)
> مسار التكلفة الجافة** — `tools/acceptance_run.py` قرب مسار المال بمزودين
> محاكَين. الرُتبتان ٢–٣ وظيفة CI مطلوبة (`e2e-live-shape`)؛ أيّ PR يمسّ
> `web/index.html` أو مسار تصدير/تقرير لا يُدمَج بلا تدفّق Playwright أخضر.
> الخطوات أدناه (على النشر الحيّ بمفاتيح حقيقية) تبقى الإثبات النهائي بعد
> النشر — نقرة المالك الوحيدة، صفرية التكلفة، متوقّعة النجاح.

افترِض المتغيرات التالية (بدّلها بقيم نشرك):

```bash
export BASE="https://<your-deployment>"      # أصل الخدمة
export KEY="<SILK_API_KEY>"                    # نفس المفتاح المضبوط في البيئة
H() { printf 'X-API-Key: %s' "$KEY"; }         # ترويسة المصادقة
```

---

## الخطوة ١ — شغّل بحث تمور × هولندا (Step 1 — run the /research)

```bash
curl -sS -X POST "$BASE/research" -H "$(H)" -H 'Content-Type: application/json' \
  -d '{"product":"تمور","market":"Netherlands","hs_code":"080410","persist":true}' \
  | tee /tmp/research_nld.json | python3 -m json.tool | head -40
```

- `persist:true` يحفظ التشغيلة فيصبح لها `analysis_id` تُبنى عليه بقيّة الخطوات.
- `hs_code` صريح يتخطّى المُحلِّل (لا اختلاق رمز عند تعذّر الحلّ).
- التشغيلة الكاملة قد تستغرق دقائق (١٢ بعثة + محلل + توليف + كاتب/مراجع). إن
  أردت ألّا يُبقي الطلب المتصفّح معلّقاً، أضِف `"async_run":true` ثم استعلم:
  `curl -sS "$BASE/research/<id>/status" -H "$(H)"`.

**بوابة الميزانية (H6).** إن ضبطت `SILK_PAID_DAILY_USD_CAP` وكان
(المُنفَق اليوم + `SILK_RESEARCH_EXPECTED_USD`) يتجاوزه، يُرفض البدء بـ`429`
و`"error":"daily_usd_budget_exhausted"` قبل أي إنفاق — والحجز ذرّي فلا تمرّ
تشغيلتان متزامنتان معاً (راجع «سؤالا التزامن والدقّة» في وصف الـPR).

التقِط `analysis_id`:

```bash
export ID=$(python3 -c "import json;print(json.load(open('/tmp/research_nld.json'))['analysis_id'])")
echo "analysis_id = $ID"
```

إن نسيت المعرّف لاحقاً، اسرد التحليلات المحفوظة وابحث عن هولندا:

```bash
curl -sS "$BASE/analyses" -H "$(H)" | python3 -m json.tool
```

---

## الخطوة ٢ — إعادة توليد التقرير الرخيصة (Step 2 — cheap regen)

هذه النقطة تُنقِذ تشغيلةً كاملة كلّفتك دولارات حين يفشل الكاتب وحده (مهلة/شبكة)
بينما نجح كل شيء آخر — بتكلفة **نداء كاتب واحد** بدل إعادة البحث كله. وهي مصدر
اختبارٍ رخيص لإصلاحات مهلة/تصعيد الكاتب.

### البيئة الموصى بها — محاولة واحدة مُقيَّدة مقابل تصعيد

كاتب التقرير يبدأ بسقف إخراج `SILK_WRITER_MAX_TOKENS` (٨٠٠٠ افتراضياً)، وعند
اقتطاع `stop_reason=max_tokens` يُضاعف السقف ويعيد المحاولة حتى
`SILK_MAX_TOKENS_RETRIES` (٣) أو `SILK_MAX_TOKENS_CEILING` (١٦٠٠٠) — أيّهما
أوّلاً. كل محاولة نداءٌ متتبَّع مستقلّ، ورموزها كلها تُحتسب في التكلفة.

| الهدف | البيئة على الخادم | الأثر |
|---|---|---|
| **محاولة واحدة مُقيَّدة** (لعرض سلوك الاقتطاع/فشل H1 بأرخص ثمن) | `SILK_MAX_TOKENS_RETRIES=0` | نداء كاتب واحد بلا تصعيد؛ إن اقتُطِع عاد أوفى نصّ جزئي أو فشل |
| **تصعيد كامل** (السلوك الإنتاجي — تقرير مكتمل مهما طال) | `SILK_MAX_TOKENS_RETRIES=3` (الافتراضي)، ورفع `SILK_MAX_TOKENS_CEILING` إن لزم | يضاعف السقف حتى يكتمل التقرير أو يبلغ السقف الصلب |

> اضبط هذه في بيئة النشر (Railway variables) ثم أعد النشر — لا تُمرَّر في جسم
> الطلب. طبقة الكاتب فقط تُصعِّد؛ باقي مواقع النداء أُحاديّة الطلقة عمداً
> (قرار #91 المُوثَّق في `DEEP_RESEARCH_DECISIONS.md`).

### نداء إعادة التوليد

```bash
curl -sS -X POST "$BASE/analyses/$ID/report" -H "$(H)" \
  | tee /tmp/regen_nld.json | python3 -m json.tool
```

**شكل النجاح المتوقَّع** (التقط والصِق هذا):

```json
{
  "report": "## 1. الخلاصة التنفيذية ...",   // نص ماركداون بأحد عشر قسماً معنوناً
  "regenerated": true,
  "review_cycles": 1,
  "unresolved_notes": []
}
```

- تحقّق أن `report` نصّ فعليّ (لا `null`) وأنه يحوي عناوين `## 1.` … `## 11.`.
- `regenerated:true` يعني أن السجل المخزَّن حُدِّث بالتقرير الجديد.

**شكل الفشل المتوقَّع** (حارس H1 — التقرير السابق محفوظ):

```json
{
  "report": null,
  "regenerated": false,
  "note": "تعذّرت إعادة توليد التقرير هذه المرة؛ التقرير السابق محفوظ كما هو دون تغيير.",
  "failure_reason": "بلغ التوليد الحدّ الأقصى للطول"   // مُعرَّب، بلا رموز داخلية
}
```

- **ما يجب أن يُلتقط ويُلصق عند الفشل** كي يكون بلاغاً قابلاً للتشخيص:
  1. جسم الردّ كاملاً (`/tmp/regen_nld.json`).
  2. رمز الحالة: `curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/analyses/$ID/report" -H "$(H)"`.
  3. أثر التشغيلة: `data/traces/<trace_id>.jsonl` (المعرّف في
     `deep_research.trace_id` من الخطوة ١) — يوضّح هل بلغ الكاتب مهلته
     الموسّعة فعلاً أم فشل أسرع، ويعرض أحداث `draft` / `draft_escalate1…`.
  4. تأكيد سلبيّ مهم: **يجب ألّا يظهر** في `failure_reason` أيٌّ من
     `empty_response` أو `stop_reason` أو `max_tokens` أو «راجع سجلّات الخادم»
     (حارس H4 يُعرِّبها/يحذفها). ظهور أيٍّ منها = ارتداد يُبلَّغ.
- **الضمانة الحاسمة (H1):** فشل إعادة التوليد **لا يطمس** تقريراً سابقاً
  ناجحاً — `GET /analyses/$ID/report.md` يظلّ يُعيد التقرير القديم كاملاً. تحقّق:

```bash
curl -sS "$BASE/analyses/$ID/report.md" -H "$(H)" | head -30
```

---

## الخطوة ٣ — قائمة الالتقاط بعد النجاح (Step 3 — post-success capture checklist)

بمجرّد أن تُنتِج الخطوتان ١–٢ تقريراً حقيقياً كاملاً، أغلِق حلقة الإثبات
بثلاثة التزامات (كلٌّ في الريبو، لا قنوات مرفقات — القاعدة §10.6):

### ٣أ — أول عيّنة حقيقية (first real sample)

استبدل عيّنة البحث المموّهة بطبعة من هذه التشغيلة الحقيقية. أعِد توليد عيّنات
البحث العميق من نفس النتيجة المخزَّنة (لا تدوير يدوي):

```bash
python3 tools/gen_research_sample.py        # samples/research_report_latest.docx (تقرير المدقّق)
python3 tools/gen_client_report_sample.py   # samples/client_report_latest.docx (تقرير العميل)
git add samples/
git commit -m "samples: أول طبعة بحث عميق حيّة — تمور × هولندا (أرقام حقيقية)"
```

> راجع `samples/README.md` لأيّ مولّد يُنتِج أيّ ملف. إن كانت الطبعة من مدخلات
> حيّة تحوي أسماء/جهات اتصال حقيقية، موّه ما يلزم قبل الالتزام (سياسة العيّنات).

### ٣ب — أول حالة ذهبية (first golden case) برقم Comtrade حيّ موثّق يدوياً

`evals/golden_cases.json` لا يزال `[]`. أضِف أول صفّ برقمٍ **تسحبه أنت** مباشرة
من Comtrade (لا من تقرير كلود)، ووثّقه يدوياً مقابل مصدره:

```bash
python3 -c "
from silk_data_layer import comtrade_trade, primary_value
recs = comtrade_trade('080410', 528, 2023, flow='M', partner=0)   # 528 = M49 هولندا
total = sum(v for v in (primary_value(r) for r in (recs or [])) if v)
print('هولندا، استيراد التمور HS080410، 2023:', total, 'USD')
"
```

ثم أضِف الحالة وفق `evals/golden_cases.schema.json` — كل رقم في `expected`
يحمل `source_url` حقيقياً (رابط Comtrade الذي استعلمت منه فعلاً، لا رابط عام):

```json
[{
  "key": "netherlands_dates", "product": "تمور", "market": "هولندا",
  "hs_code": "080410",
  "expected": {"trade_import_usd": {"value": <الرقم من الأمر أعلاه>, "year": 2023,
               "source_url": "https://comtradeplus.un.org/..."}},
  "verified_at": "<تاريخ اليوم>", "verified_by": "<اسمك>"
}]
```

شغّل التقييم لتسجيل خط الأساس الأول ثم التزم:

```bash
python3 -m silk_evals --case netherlands_dates    # أول تشغيلة: regression=false دوماً (لا أساس سابق)
git add evals/golden_cases.json evals/scores.json
git commit -m "evals: أول حالة ذهبية — هولندا/تمور برقم Comtrade موثّق يدوياً"
```

### ٣ج — تحديث سِجلّ القرارات (#84 → هذا الـPR)

القيد #84 في `docs/DEEP_RESEARCH_DECISIONS.md` سجّل أن `golden_cases.json`
بقي `[]` لعدم وجود رقمٍ مُتحقَّق منه يدوياً بعد. بعد إتمام ٣ب، أضِف قيداً
لاحقاً يوثّق أن أول حالة ذهبية حقيقية سُجِّلت (هولندا/تمور)، ويُحيل صراحةً من
#84 إلى هذا الـPR كإغلاق للفجوة — بنفس أسلوب القيود (مرساة file:line، «غير
موجود» يُذكر صراحة، لا ادّعاء تحقّق زائف).

---

## ملخّص الضمانات التي يثبتها هذا الدليل

| الخطوة | تثبت |
|---|---|
| ١ | المسار الحيّ يُنتِج تشغيلة بحث كاملة بأرقام مصادر حقيقية، وبوابة الميزانية الدولارية (H6) تحرس البدء ذرّياً |
| ٢ | إعادة التوليد الرخيصة تنجح؛ وعند فشل الكاتب لا يُطمَس تقرير سابق ناجح (H1) والسبب مُعرَّب بلا رموز داخلية (H4) |
| ٣ | حلقة الإثبات مُغلَقة: عيّنة حقيقية + حالة ذهبية برقم موثّق يدوياً + سجلّ قرارات محدَّث |

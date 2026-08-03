# تدقيق أعطال الخدمات الخارجية — External-service silent-failure audit

> **عائلة C (Wave 1.5) — «الفشل الصامت لخدمةٍ خارجية».** عضوٌ واحدٌ معروف
> (scraper-silent-fail)؛ هذا التدقيق يُعمّم العائلة: **كلُّ** نداءٍ خارجيٍّ
> يُعدَّد، ويُتحقَّق أنّ فشله يُعلَن للمشغّل في جدول `ops_errors` (نوع موحّد
> `service_failure` عبر `silk_ops_log.record_service_failure`)، لا أن يبتلعه
> `log.warning` وحده. طريقة التدقيق: قراءة فقط، بالدليل file:line، «غير موجود»
> يُذكر صراحةً (منهج `docs/AUDIT_STATUS.md`).

**القاعدة الجديدة:** فشلُ خدمةٍ خارجية **مُهيَّأة** يجب أن يترك أثرًا في
`ops_errors` — فلا «لا نتيجة» صامت يخدع المشغّل («المكشطة مضبوطة والهاتف —» —
البلاغ الأصلي). العطلُ يبقى **تعطيلًا نظيفًا** للعميل (فجوة معلنة في DataPoint)
**و**سطرًا تشخيصيًا للمشغّل في آنٍ واحد.

## الجدول — service → failure path (file:line) → ops-log status

| الخدمة | مسار الفشل (file:line) | قبل | بعد (هذا الـPR) |
|---|---|---|---|
| **Scraper** (خرائط/جهات اتصال) | `silk_gmaps.submit_scrape` (`silk_gmaps.py:148`)، `_fetch_job` (`silk_gmaps.py:171`) | صامت (`log.warning` فقط) | ✅ `record_service_failure("scraper", …)` — مرحلتا submit/fetch |
| **GDELT** (أخبار مخاطر) | `silk_gdelt_agent` main except (`silk_gdelt_agent.py:77`) | صامت | ✅ `record_service_failure("gdelt", …)` |
| **Google Trends** (موسمية) | `silk_trends_agent.trends_interest` except (`silk_trends_agent.py:54`) | صامت | ✅ `record_service_failure("trends", …)` |
| **Eurostat** | `silk_eurostat_agent` fetch except (`silk_eurostat_agent.py:98`) | صامت | ✅ `record_service_failure("eurostat", …)` |
| **OpenAlex** | `silk_openalex_agent` fetch except (`silk_openalex_agent.py:68`) | صامت | ✅ `record_service_failure("openalex", …)` |
| **FAOSTAT** | `silk_faostat_agent` fetch except (`silk_faostat_agent.py:122`) | صامت | ✅ `record_service_failure("faostat", …)` |
| **Google Maps** (وكيل) | `silk_maps_agent` fetch except (`silk_maps_agent.py:56`) | صامت | ✅ `record_service_failure("maps", …)` |
| **Vision** (استقبال الصورة) | `silk_product_intake._vision_extract` (رد فارغ) (`silk_product_intake.py:145`) | صامت | ✅ `record_service_failure("vision", …)` |
| **Comtrade** (تجارة) | `silk_data_layer.comtrade_trade` except (`silk_data_layer.py:~316`) | فجوة معلنة (`DataPoint` note) + عدّاد `live_fetches` (`silk_context`) | ⏳ **مقصود**: نداءٌ متعدّد التوزيع (~١٥٠/تحليل) — إعلانُ كلِّ فشلٍ في `ops_errors` (حلقةٌ مسقوفة) يُغرِقها؛ يبقى مُعلَنًا عبر ملاحظة DataPoint + عدّاد `live_fetches`. يُراجَع إن أراد المالك إعلانًا خشِنًا لكل تشغيلة. |
| **World Bank** (مؤشرات) | `silk_data_layer.world_bank` / `_wb_*` (`silk_data_layer.py`) | فجوة معلنة (`DataPoint` note) + عدّاد | ⏳ **مقصود** (نفس منطق Comtrade — نداءٌ متكرّر) |
| **IMF WEO** (اقتصاد كلي) | `silk_imf_agent.imf_indicator` fetch except / None (`silk_imf_agent.py`) | جديد (الموجة: دمج مصادر جديدة) | ✅ `record_service_failure("imf", …)` — نداءٌ منخفض التردّد (٣ مؤشرات/تحليل)، فإعلانُ فشله لا يُغرِق الحلقة |
| **WTO TTD** (تعريفة) | `silk_wto_tariff.wto_applied_tariff` fetch except / None (`silk_wto_tariff.py`) | جديد (الموجة: دمج مصادر جديدة) | ✅ `record_service_failure("wto_ttd", …)` — بلا مفتاح => فجوة معلنة صفريّة النداء (لا فشلَ يُعلَن، الخدمة غير مُهيَّأة فقط) |
| **LocalPrice / Volza / Explee** (مدفوع) | `silk_localprice_agent` / `silk_volza_agent` / `silk_explee_agent` | فجوة معلنة (`DataPoint`) داخل `/deepen` فقط | ⏳ **لاحقًا**: مسارٌ مدفوعٌ محصور بـ`/deepen` (نادر، محجوز مسبقًا)؛ إعلانُه للمشغّل بند تحسينٍ منفصل |

## القرار الهندسي (مُوثَّق، ليس فجوةً منسيّة)

- **الخدمات المتقطّعة (نداءٌ واحدٌ لكلِّ تحليل)** — scraper/gdelt/trends/eurostat/
  openalex/faostat/maps/vision — **تُعلَن الآن** في `ops_errors` (فشلٌ واحدٌ =
  سطرٌ واحد، بلا إغراق).
- **خدمات الجلب عالية التردّد** — Comtrade/World Bank (fan-out ~١٥٠ نداء/تحليل)
  — تبقى مُعلَنةً عبر **ملاحظة `DataPoint`** (سطح العميل) + **عدّاد
  `data_economics.live_fetches`** (سطح المشغّل)؛ إعلانُ كلِّ فشلٍ في حلقة
  `ops_errors` المسقوفة يُغرِقها ويطمس الإشارات المتقطّعة. **بندٌ مفتوحٌ
  موثَّق**: إعلانٌ خشِنٌ (مرّة/خدمة/تشغيلة) عند طلب المالك.

## الإنفاذ

- `silk_ops_log.record_service_failure(service, reason, context)` — نوع موحّد
  `service_failure` مع اسم الخدمة في السياق (فرزٌ بنوعٍ واحد).
- `tests/test_wave1p5_service_failure_ops.py` — قفلٌ سلوكيّ: فشلُ الـscraper
  (وعيّنةُ وكيلٍ) يكتب صفَّ `service_failure` فعليًّا في `ops_errors` مؤقّت.
- سجلّ الانحدار: عائلة `silent-external-failure` (`test_regression_registry.py`).

## تشخيص المكشطة (Wave 2، البند ٧) — «المكشطة مضبوطة والهاتف —»

**السؤال:** لماذا خرج هاتفُ رائدِ الخرائط «—» رغم ضبط `SILK_GMAPS_SCRAPER_URL`؟

**التشخيص (بالدليل):** حالتان متمايزتان الآن، لم تكونا كذلك قبل:
1. **المكشطة فشلت فعلًا** (submit/fetch رمى استثناءً): يترك أثرًا في `ops_errors`
   نوع `service_failure` باسم `scraper` (`silk_gmaps.py:148,171` بعد Wave 1.5 C).
   المشغّل يراه فورًا — لا «لا نتيجة» صامت.
2. **المكشطة نجحت لكن هذا النشاط بلا هاتف** في مصدر الخرائط: فجوةٌ بياناتٍ
   **متوقّعة** ومعلنة «—» في الخلية (لا فشل خدمة) — لا يُسجَّل في `ops_errors`
   لأنه ليس عطلًا. البلاغ الأصلي («الهاتف —») كان غالبًا هذه الحالة (أو الحالة ١
   قبل أن تصبح مرئية).

**القاعدة:** غيابُ الحقل يبقى «—» صادقًا (عقد عدم الاختلاق)؛ فشلُ **الخدمة**
يصير سطرًا في `ops_errors`. فمن جدول العمليات وحده يُميَّز «الخدمة فشلت» من
«الخدمة نجحت وهذا النشاط بلا هاتف» — لا لبس بعد اليوم.

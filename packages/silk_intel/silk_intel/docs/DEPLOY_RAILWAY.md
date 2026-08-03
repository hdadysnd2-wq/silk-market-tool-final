# النشر على Railway — Deploying Silk on Railway

خدمة Railway واحدة تشغّل كل شيء: `api.py` يقدّم الـ API **والواجهة معًا** (`web/` تُقدَّم على `/`)، فلا حاجة لخدمة واجهة منفصلة.
*A single Railway service runs everything: `api.py` serves both the API and the dashboard (`web/` mounted at `/`).*

المستودع مهيأ بالكامل — Railway يكتشف `Dockerfile` تلقائيًا ويقرأ `railway.json` (فحص صحة على `/health`، إعادة تشغيل عند الفشل).
*The repo is fully pre-configured: Railway auto-detects the `Dockerfile` and reads `railway.json` (healthcheck on `/health`, restart on failure).*

---

## ١ · إنشاء الخدمة — Create the service

1. افتح [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub repo** → اختر هذا المستودع، فرع `main`.
2. Railway يبني الصورة من `Dockerfile` ويشغّل `uvicorn api:app --host 0.0.0.0 --port $PORT` (متغير `PORT` يُمرَّر تلقائيًا).
3. **Settings → Networking → Generate Domain** للحصول على رابط عام (`https://….up.railway.app`).

## ٢ · القرص الدائم — Persistent volume (مهم · important)

نظام ملفات Railway **زائل**: بدون قرص دائم تضيع مع كل نشر جديد **أربعة** مخازن — `silk.db` (سجل التحليلات التراكمي)، `silk_store.db` (مخزن الحقائق: تدفقات كومتريد + مؤشرات البنك الدولي المجموعة)، `usage.db` (عدّاد السقف المدفوع)، و`cache/` (ذاكرة طلبات GET) — فيُعاد دفع ثمن الجلب نفسه بعد كل نشر.
*Railway's filesystem is ephemeral — without a volume, all four stores (analyses DB, fact store, usage counter, request cache) are wiped on every redeploy and the same fetches are paid for again.*

1. على الخدمة: **Right-click → Attach Volume** (أو ⌘K → Volume)، واضبط **Mount Path** إلى `/data`. (القرص إعداد خدمة في اللوحة — لا يُعلن في `railway.json`.)
2. أضف متغيّر بيئة واحدًا يوجّه كل المخازن للقرص:

| المتغير | القيمة |
|---|---|
| `SILK_DATA_DIR` | `/data` |

يشتقّ منه تلقائيًا: `/data/silk.db` و`/data/silk_store.db` و`/data/usage.db` و`/data/cache/`. المتغيرات الصريحة (`SILK_DB`, `SILK_STORE_DB`, `SILK_USAGE_DB`, `SILK_CACHE_DIR`) تبقى مدعومة وتفوز عليه فرادى.
*One var derives all four paths; the explicit per-store vars still win individually.*

3. تحقّق بعد النشر: `GET /health` يعيد قسم `storage` بالمسارات المحلولة فعليًا — يجب أن تقع كلها تحت `/data`.
*Verify: `GET /health` now returns a `storage` section with the resolved paths — all should live under `/data`.*

> ⚠️ **لا** تركّب القرص على `/app/data` — المجلد `data/` في المستودع يحوي ملفات CSV مرجعية (بذرة HS، `requirements_l1.csv`) سيحجبها القرص الفارغ ويكسر المحلّل والامتثال. القرص على `/data` والمسارات تُوجَّه بالمتغيرين أعلاه.
> *Never mount the volume over `/app/data` — that directory ships seed CSVs the resolver and compliance agent read; an empty volume would shadow them. Mount at `/data` and redirect via the two env vars.*

## ٣ · متغيّرات البيئة — Environment variables (Variables tab)

القائمة الكاملة مع الشرح في `.env.example`. الأساسية للإنتاج:
*Full annotated list in `.env.example`. Production essentials:*

| المتغير | إلزامي؟ | الغرض |
|---|---|---|
| `SILK_API_KEY` | **نعم في الإنتاج — إلزامي** | مصادقة `X-API-Key` على `/analyze` و`/deepen` **وعلى نقاط قراءة التحليلات المحفوظة** (`/analyses`, `/analyses/{id}`, `/brief`, `/report.docx` — إصلاح C-1). **بدونه القراءةُ مفتوحة للعموم بالتعداد وكل الحماية شكلية** — اضبطه أولاً. |
| `SILK_PAID_DAILY_CAP` | ينصح به | سقف تفعيلات الطبقات المدفوعة يوميًا (429 عند التجاوز؛ يفشل مغلقاً عند خطأ العدّاد — M-2) |
| `SILK_RATE_LIMIT` / `SILK_RATE_WINDOW` | اختياري | حدّ المعدّل بالذاكرة (الافتراضي 120 طلباً/60 ثانية؛ 0 يعطّله — M-1) |
| `SILK_DATA_DIR` | نعم (مع القرص) | توجيه كل المخازن (silk.db، silk_store.db، usage.db، cache/) للقرص الدائم (§٢ أعلاه) |
| `SILK_DB` / `SILK_STORE_DB` / `SILK_USAGE_DB` / `SILK_CACHE_DIR` | اختياري | توجيه مخزن بعينه لمسار مختلف — يفوز على `SILK_DATA_DIR` |
| `COMTRADE_API_KEY` | اختياري | يرفع حد Comtrade إلى ~500 طلب/يوم |
| `GOOGLE_MAPS_API_KEY`, `SEARCH_API_KEY` | اختياري | طبقات الإثراء المجانية بحصة |
| `VOLZA_API_KEY`, `EXPLEE_API_KEY`, `ANTHROPIC_API_KEY` | اختياري (مدفوع) | طبقات `/deepen` والحكم الذكي — **لا تضبطها دون `SILK_API_KEY`** |
| `CORS_ORIGINS` | اختياري | فقط إن نُشرت الواجهة على دومين منفصل (Netlify) |

## ٤ · التحديث الدوري — Scheduled refresh (اختياري · optional)

أضف متغيّرًا واحدًا لتفعيل تحديث المخزن الدوري داخل الخدمة نفسها:
*One variable turns on the periodic store refresh, in-process:*

| المتغير | القيمة | الأثر |
|---|---|---|
| `SILK_REFRESH_HOURS` | `24` | كل ٢٤ ساعة: مؤشرات البنك الدولي جماعيًا + تسخين مسبق لتدفقات Comtrade (رموز HS المطلوبة مؤخرًا × أسواق الأولوية، السنة المغلقة الأخيرة) |

- التسخين يعمل بميزانية Comtrade اليومية الصلبة نفسها (`COMTRADE_DAILY_BUDGET`) مع backoff يحترم `Retry-After`، ويترك احتياطيًا للطلبات الحية (`SILK_REFRESH_BUDGET_RESERVE`، افتراضي 150) — لا اندفاع على المصادر أبدًا.
- التحليل الحي التالي لنفس `hs+سوق+سنة` يُخدم من المخزن بصفر نداء — وهذا يعالج مباشرة مشكلة التقارير الفارغة بسبب حدّ المعدل.
- **لماذا ليس خدمة cron منفصلة؟** قرص Railway الدائم يُركَّب على **خدمة واحدة فقط** — خدمة منفصلة لا ترى `/data` نفسه فتملأ مخزنًا لا يقرأه أحد. لذا يعمل التحديث خيطًا خلفيًا داخل خدمة الويب. (للتشغيل اليدوي: `railway ssh` ثم `python3 silk_collectors.py`.)
- *Why not a separate cron service? A Railway volume mounts to ONE service; a separate job could not share `/data`. The refresh therefore runs as a daemon thread inside the web service. Manual run: `railway ssh` → `python3 silk_collectors.py`.*

## ٥ · التحقق — Verify

```
https://<domain>/health   → {"status":"ok"}   (+ تحذير إن وُجد مفتاح مدفوع بلا SILK_API_KEY)
https://<domain>/          → الواجهة (اترك حقل «رابط الباك-إند» فارغًا — نفس الخدمة)
```

جرّب تحليلًا من الواجهة ثم أعد النشر (Redeploy) وتأكد أن التحليل ما زال في القائمة — هذا يثبت أن القرص الدائم يعمل.
*Run one analysis, redeploy, and confirm it still appears in the list — that proves the volume works.*

## ملاحظات — Notes

- كل push إلى `main` ينشر تلقائيًا (افتراضي Railway؛ يمكن تقييده بـ **Check Suites** ليننتظر نجاح CI).
- ترحيل من Render: هذا الدليل يحلّ محل `render.yaml` (حُذف). لا ترحيل بيانات تلقائي — إن كانت لديك `silk.db` قديمة على قرص Render انسخها إلى قرص Railway عبر `railway ssh` / `scp` قبل إيقاف الخدمة القديمة، فسجل التحليلات تراكمي ولا يُحذف (قاعدة المستودع).
- *Migrating from Render: this guide replaces the deleted `render.yaml`. No automatic data migration — copy any existing `silk.db` from the old Render disk onto the Railway volume before decommissioning; the analyses track record is cumulative and must never be lost.*

## ٦ · بوابة قبول PDF/RTL قبل الإصدار — PDF/RTL release-acceptance gate (§3/§4)

المُسلَّم النهائي PDF غير قابل للتحرير (§3)، وكامله RTL (§4). محرّك التحويل
(LibreOffice/`soffice`) وخطّ عربي الشكل يجب أن يكونا حاضرين على النشر — وهذا
**لا يُلتقَط هرمتياً**.

**مثبَّتان في الصورة (`Dockerfile`):** `libreoffice-writer` + `fonts-hosny-amiri`
+ `fontconfig` يُثبَّتان وقت البناء، فيتوفّر `soffice` وخطّ Amiri العربي على
النشر ويعمل زرّ «تصدير التقرير (PDF)» حيّاً (لا فرع 503). نفس التبعية مثبَّتة
في وظيفة CI `e2e-live-shape` كي يؤكّد المتصفّح الحقيقي توقيع `%PDF`. عند ترقية
صورة الأساس تحقّق أن الحزمتين ما زالتا تُثبَّتان (`soffice --version` و
`fc-list | grep -i amiri`). قبل أي إصدار:

1. **على النشر الحيّ**: `python3 tools/post_deploy_smoke.py https://<host> --key <SILK_API_KEY>`
   — الخطوة ٥ تضرب `GET /analyses/{id}/report.pdf` فعلياً (٥٠٣ = محرّك التحويل
   غائب). يجب أن يعيد توقيع `%PDF`.
2. **على التجهيز/الـstaging** (حيث `soffice` وخطّ عربي مثبّتان):
   `SILK_PDF_ACCEPTANCE=1 python3 -m pytest tests/test_report_output_overhaul.py::test_pdf_rtl_geometry_and_arabic_font -q`
   — يفشل **بصوتٍ عالٍ** إن غاب الخطّ العربي أو محرّك التحويل أو أداة قياس
   الـPDF (pdfplumber/pdftotext)، ويقيس أن ≥٩٥٪ من الأسطر القصيرة المتعرّجة
   تنحاز يميناً (الفحص الحاسم لانقلاب `jc` المنطقي في الـPDF المُصيَّر).
   **لا يجوز أن يبقى هذا الاختبار مُتخطّى قبل الإصدار** — خطّ النشر يضبط
   `SILK_PDF_ACCEPTANCE=1` فيتحوّل التخطّي إلى فشل صريح.

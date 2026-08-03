# منصة سِلك لذكاء الأسواق — Silk Market Intelligence

> نظام **متعدد الوكلاء** لتحليل أسواق التصدير/الاستيراد لشركة سِلك (منتجات سعودية)،
> يجمّع ويحلّل **بيانات حقيقية فقط** ويوسم كل معلومة بمصدرها ودرجة ثقتها.

A multi-agent system that ranks export markets for Saudi products using **real public data only**
(UN Comtrade + World Bank). Every value is tagged with its source and a confidence score.

---

## المبدأ التأسيسي · Founding principle

النظام **لا يخلق بيانات** — بل يجمّع ويحلّل المتاح آلياً. الوكيل بلا مصدر حقيقي = خيال مقنع.
عند فشل المصدر، تُعاد قيمة فارغة موسومة (`value=None, confidence=0.0`) مع تحذير — **ولا يُخترع رقم**.

The system never fabricates data. On a source failure it returns a provenance-tagged empty value
(`DataPoint(value=None, confidence=0.0, note=...)`) and logs a warning — it never invents a number.

---

## البنية · Architecture

| الملف · File | الوظيفة · Role |
|---|---|
| `silk_data_layer.py` | الطبقة الأساس: ربط UN Comtrade + World Bank، وتعريف `DataPoint` (المصدر/الثقة). |
| `silk_data_layer_v2.py` | + القوة الشرائية (PPP) + المنافسون بالاسم وحصصهم. |
| `silk_hs_resolver.py` | تصنيف HS تلقائي من اسم المنتج (عربي/إنجليزي) عبر `difflib` + الكلمات المفتاحية. |
| `silk_agents.py` | بنية الوكلاء: مدير + 3 وكلاء باحثين (تجارة/اقتصاد/منافسة) + لجنة تحكيم. |
| `silk_market_ranker.py` | محرّك الترتيب: يقارن عدة دول لرمز HS ويرتّبها بنقاط شفّافة قابلة للتدقيق. |
| `silk_engine.py` | **المحرّك الكامل**: يقبل أي منتج بالاسم → يصنّفه → يرتّب أسواقه. ابدأ من هنا. |
| `silk_trends_agent.py` | وكيل اختياري: إشارة الطلب من Google Trends (`pytrends`) مع موسمية. يتدهور بأمان بلا الحزمة/الشبكة. |
| `silk_tariffs_agent.py` | وكيل اختياري: التعريفة الجمركية المطبّقة (%) من World Bank WITS. لا يخمّن نسبة عند الفشل. |
| `silk_quality.py` | فحوص جودة (stdlib): يوسم الصفوف بتنبيهات (حجم شبه صفري، نواقص، قيم خارج المدى) — **لا يغيّر أرقامًا**. |
| `silk_storage.py` | تخزين النتائج في SQLite (stdlib): `save_analysis`/`get_analysis`/`list_analyses`. ملف `.db` متجاهَل في git. |
| `silk_faostat_agent.py` | وكيل اختياري: نصيب الفرد من العرض الغذائي (FAOSTAT). يتدهور بأمان عند المصادقة/الفشل (لا يخمّن رقمًا). |
| `silk_cache.py` | ذاكرة تخزين مؤقت على القرص لطلبات GET (stdlib؛ `requests` بكسل). يُستخدم شفّافًا في طبقة البيانات. |
| `silk_maps_agent.py` | وكيل اختياري: أعمال حقيقية بالاسم والتقييم (Google Places). بلا مفتاح: `None` موسوم. |
| `silk_websearch_agent.py` | وكيل اختياري: نتائج ويب حقيقية (Serper.dev). بلا مفتاح: `None` موسوم. |
| `silk_localprice_agent.py` | وكيل مدفوع: أسعار تجزئة فعلية + مقارنة سعرك (`compare_own_price`). |
| `silk_volza_agent.py` | وكيل مدفوع: مستوردون بالاسم من بوالص الشحن (Volza). |
| `silk_explee_agent.py` | وكيل مدفوع: مشترون وجهات اتصال B2B (explee، امتثال GDPR/PDPL). |
| `silk_ai_judge.py` | أدوات كلود المشتركة (`_call`/العزل) + مُعِدّ التقرير (`ai_report`) — الحكم نفسه صار حصراً عبر `silk_synthesis` (§9.3). |
| `silk_usage.py` | عدّاد الاستهلاك المدفوع اليومي (سقف 429) — ملف مستقل عن `silk.db`. |
| `silk_competitors_agent.py` | وكيل الموجة ٣: مرشّحو منافسين **بالاسم** (شركات لا دول) من بحث الويب — موسومون "غير مُتحقَّق". |
| `silk_channels_agent.py` | وكيل الموجة ٣: مرشّحو قنوات التوزيع (فعلي + رقمي بعدستين في وكيل واحد). |
| `silk_importers_agent.py` | وكيل الموجة ٣: مرشّحو مستوردين (طبقة ويب مجانية؛ الأسماء الموثّقة عبر `/deepen`/Volza). |
| `silk_requirements_agent.py` | وكيل الاشتراطات (الموجتان ٣+٥ب): قائمة تحقق ثنائية الاتجاه من مرجع الطبقة ١ (خليج + **سلسلة القرار الأوروبية بلوائحها المرقّمة من EUR-Lex**، الأهلية أولاً للحيواني المصدر) + تصنيف «قابلية التقنين» ظاهر على القائمة + طبقة ٢ تحقق حي مستهدف اختيارية. |
| `silk_context.py` | سياق `/deepen` (contextvars) — حارس `BaseAgent` البنيوي للوكلاء المدفوعين. |
| `correlation.py` | **محرّك التقاطع** (الموجة ٤): يربط نتائج الوكلاء بالذاكرة حول بطاقة منتجك — خيوط منافسين/جدوى/أبواب دخول/جهات. **صفر استدعاءات خارجية** (اختبار بنيوي يثبته)؛ الخيط الناقص يُعلن لا يُخترع. |
| `silk_synthesis.py` | التوليف ثنائي المرحلة (الموجة ٤): لجنة حتمية (مرحلة ١) + حكم كلود المعزول (مرحلة ٢، ببرومبت "المواجهة" عند وجود الخيوط) — **المدخل الوحيد للحكم** (الازدواجية حُذفت، §9.3). |
| `silk_discovery.py` | **اكتشاف الفرص المعكوس** (الموجة ٥أ): "عندي سوق — ما المطلوب فيه؟" — إشارات من Comtrade + trends القائمين حصراً (صفر مصادر جديدة)؛ القرب اللوجستي فجوة معلنة لا محسوبة. |
| `silk_reports.py` | مشتقا التقارير (الموجة ٥ج): **التقرير الكامل Word** (§10.3 — خلاصة أولاً، سطر مصدر تحت كل رقم، «حدود هذا التقرير» قبل التوصيات) و**المختصر** (§10.4 — صفحة «رسالة جوال») — كلاهما من القالب الموحّد حصراً. |
| `silk_render.py` | **القالب الموحّد** (§10.1): `build_view` نموذج العرض القانوني الوحيد — اللوحة والطرفية وStreamlit والمختصر كلها مشتقات منه. |
| `api.py` | واجهة REST عبر FastAPI فوق المحرّك (تُستورد FastAPI بكسل؛ `app=None` بدونها). |
| `tools/dev_console.py` | أداة مطوّر (Streamlit) فوق المحرّك — ليست واجهة المنتج؛ يُعاد تقييم حذفها في M9. |
| `tools/fetch_hs_codes.py` | أداة تشغيل: تجلب مرجع HS من Comtrade وتوسّع `data/hs_codes.csv` برموز حقيقية. |
| `Dockerfile` · `.github/workflows/ci.yml` | تعبئة الخدمة (Docker) + تكامل مستمر (CI) يشغّل اختبارات الدخان. |
| `data/hs_codes.csv` | جدول التصنيف للمُصنّف: **5,627 صفاً** = بذرة منسّقة (عربي/إنجليزي + كلمات مفتاحية) + كامل رموز HS6 المدموجة. |
| `data/hs_reference.csv` | المرجع الكامل الخام من Comtrade (6,940 رمزاً، كل المستويات 2/4/6) للتدقيق والتوسيع. |

كل قرار من المنصة **أوّلي لا نهائي**: تصفّي الأسواق وترتّبها، ثم تُستثمر الدراسة العميقة على المرشّحين فقط.

---

## المصادر · Data sources — الطبقات الاثنتا عشرة · the 12 layers

كل المصادر **موصولة** (`wired`). المجانية تعمل بلا مفتاح (أو بمفتاح اختياري يرفع الحد)؛
المدفوعة تتطلب مفتاحًا وإلا تتدهور بأمان إلى `value=None` بلا اختلاق. خريطة الحالة الحيّة عبر `GET /sources`.

All layers are wired. Free layers work keyless (or with an optional key that raises limits);
paid layers require a key and otherwise degrade gracefully to `value=None` (no fabrication).
Live status map: `GET /sources`.

| # | الطبقة · Layer | النوع · Type | الوحدة · Module | مفتاح البيئة · Key env |
|---|---|---|---|---|
| 1 | UN Comtrade | مجاني · free | `silk_data_layer.py` | — (اختياري `COMTRADE_API_KEY`) |
| 2 | World Bank | مجاني · free | `silk_data_layer.py` | — (لا مفتاح) |
| 3 | FAOSTAT | مجاني · free | `silk_faostat_agent.py` | — (اختياري) |
| 4 | WITS (الرسوم · tariffs) | مجاني · free | `silk_tariffs_agent.py` | — (لا مفتاح) |
| 5 | Google Trends | مجاني · free | `silk_trends_agent.py` | — (`pip install pytrends`) |
| 6 | Google Maps | مجاني · free | `silk_maps_agent.py` | `GOOGLE_MAPS_API_KEY` |
| 7 | Web Search (Serper) | مجاني · free | `silk_websearch_agent.py` | `SEARCH_API_KEY` |
| 8 | أسعار التجزئة المحلية · Local retail | مدفوع · paid | `silk_localprice_agent.py` | `LOCALPRICE_API_KEY` |
| 9 | Volza | مدفوع · paid | `silk_volza_agent.py` | `VOLZA_API_KEY` |
| 10 | explee | مدفوع · paid | `silk_explee_agent.py` | `EXPLEE_API_KEY` |
| 11 | كلود (الحَكَم) · Claude (AI judge) | ذكاء · ai | `silk_ai_judge.py` | `ANTHROPIC_API_KEY` |
| 12 | مرجع الاشتراطات ط١ · Requirements L1 (خليج + سلسلة أوروبا EUR-Lex + خروج سعودي) | مجاني · free | `silk_requirements_agent.py` | — (ملف مرجعي، بلا شبكة) |

> النهايات المرجعية · reference endpoints:
> **UN Comtrade** `https://comtradeapi.un.org/public/v1/preview/C/A/HS` ·
> **World Bank** `https://api.worldbank.org/v2/country/{iso3}/indicator/{code}`.

---

## التشغيل · Quick start

```bash
pip install -r requirements.txt
python3 silk_engine.py        # عرض توضيحي: يصنّف منتجاً ويرتّب أسواقه
```

> ملاحظة: التشغيل يتطلب وصولاً للإنترنت ليجلب البيانات الحقيقية. بلا إنترنت يعمل الكود لكن يُظهر
> "لا بيانات / فشل الجلب" بدل أرقام مُختلَقة (إثباتاً لسلامة المبدأ).

---

## طبقات إضافية · Extra layers

طبقات اختيارية فوق المحرّك، **مطفأة افتراضيًا** حتى لا تتغيّر السلوك القديم ولا الاختبارات:

```python
from silk_engine import analyze
analyze("تمور",
        with_trends=True,    # Google Trends (يتطلب pytrends؛ بدونه None موسوم)
        with_tariffs=True,   # WITS applied tariff %
        persist=True,        # يحفظ في SQLite ويضيف analysis_id
        db_path="data/silk.db",
        check_quality=True)  # يضيف quality_flags (تنبيهات فقط، لا يغيّر أرقامًا)
```

- `with_trends` / `with_tariffs` / `with_faostat` **سياق إضافي فقط** — يُرفقون `row['trends']` / `row['tariff']` / `row['faostat']` ولا يغيّرون `total_score`.
- `with_maps` / `with_volza` / `with_explee` يُرفقون `row['maps']` / `row['volza']` / `row['explee']` لأعلى الأسواق؛ و`with_websearch` يُرفق `result['websearch']` على المستوى الأعلى. كلّها **إضافية** لا تغيّر `total_score`.
- `with_localprice` يُرفق `row['localprice']` (قوائم مسعّرة فعلية، مع `is_best_seller` عند توفّر شارة حقيقية من المزوّد — لا يوجد رقم "عدد المبيعات" علني من أي منصة). مع `own_price` يُرفق أيضاً `row['price_comparison']`: مقارنة سعرك بالقوائم المرصودة (نسبة كونك أرخص من السوق) — مقارنة سعرية لا مقارنة مبيعات.
- المدفوعان (Volza, explee) يتطلبان مفتاحًا؛ بدونه يُرجعان `value=None, confidence=0.0` بلا اختلاق.
- جميع الطبقات تتدهور بأمان بلا شبكة (قيمة `None` موسومة بمصدرها، بلا اختلاق رقم).

### تشغيل الواجهة · Run the UI

```bash
pip install streamlit            # حزمة اختيارية
streamlit run tools/dev_console.py   # أداة مطوّر اختيارية
```

الحزم الاختيارية: `streamlit` (للواجهة) و `pytrends` (لوكيل الاتجاهات). النواة تعمل وتُستورد بدونهما.

### تشغيل الخدمة (API) · Run the backend (API)

واجهة REST عبر FastAPI فوق المحرّك. تُستورد `api.py` بلا الحزمة (`app=None`)؛ التشغيل يحتاج `fastapi`+`uvicorn`.

```bash
pip install fastapi uvicorn      # حزم اختيارية
uvicorn api:app --host 0.0.0.0 --port 8000
# أو مباشرة:  python3 api.py
```

عبر Docker · with Docker:

```bash
docker build -t silk-api .
docker run -p 8000:8000 silk-api
```

النهايات · Endpoints:

| Method · Path | الوظيفة · Role |
|---|---|
| `GET /health` | حالة الخدمة + توفّر الحزم الاختيارية. |
| `GET /sources` | خريطة حالة الطبقات الاثنتي عشرة (`name, type, wired, key_env, key_present`). |
| `GET /resolve/{name}` | يصنّف اسم منتج إلى HS6 (مع المصدر/الثقة). |
| `POST /analyze` | المسار العادي (مجاني حصراً): `{product, year, with_trends, with_tariffs, with_faostat, with_maps, with_websearch, with_competitors, with_channels, with_importers, with_requirements, persist}` — الحقول المدفوعة تُتجاهَل بنيوياً. |
| `POST /deepen` | مسار التعميق (المدفوع الوحيد): يضيف `{with_localprice, own_price, with_volza, with_explee, with_ai}` ويعمل داخل سياق يسمح لوكلاء `PAID` بالتنفيذ. |
| `POST /trend` | **خط الاتجاه متعدد السنوات** (سنوات الدراسة): `{hs_code, market_iso3, end_year, span}` — سلسلة استيراد سنوية + نمو% + CAGR من Comtrade القائم (صفر مصادر جديدة)؛ سنة بلا بيانات = فجوة معلنة لا صفر. متاح أيضاً على `/analyze` عبر `with_trend`/`trend_span` (يُرفَق `row['trend']`). |
| `POST /discover` | **اكتشاف الفرص المعكوس** (§11): `{market_iso3, year, sector, min_import_usd, with_seasonality}` — أعلى الفرص بإشارات قابلة للتتبع (نمو الاستيراد + فجوة الحصة السعودية + موسمية تكميلية)؛ لا حشو، والفجوات معلنة. كل فرصة تحمل `hs_code` يُمرَّر مباشرة إلى `/analyze` («حلّل هذه الفرصة»). |
| — `product_card` | حقل اختياري على المسارين: `{cost_per_unit, unit, tier, monthly_capacity, shipping_per_unit}` — وجوده يشغّل محرّك التقاطع ويضيف «موقعك التنافسي»؛ والرد يحمل دوماً `view` (القالب الموحّد §10.1). |
| `GET /analyses` | يسرد التحليلات المحفوظة. |
| `GET /analyses/{id}` | يعيد تحليلًا محفوظًا، أو 404. |
| `GET /analyses/{id}/brief` | المختصر النصي (§10.4) من القالب الموحّد. |
| `GET /analyses/{id}/report.docx` | التقرير الكامل Word (§10.3) — 501 بتلميح واضح بلا python-docx. |
| `PATCH /analyses/{id}/outcome` | يسجّل النتيجة الفعلية (`{outcome}`) — سجل المصداقية التراكمي. |

**CI** (`.github/workflows/ci.yml`): يثبّت `requirements.txt` (بما فيها `fastapi`/`uvicorn`) + `pytest` ويشغّل `python -m pytest tests/ -q` عند كل push / PR.

### النشر · Deployment (Railway — خدمة واحدة)

خدمة Railway واحدة تقدّم **الواجهة + الـ API معًا** (`api.py` يضيف `web/` على `/`)، فلا حاجة لـ Netlify ولا لصق رابط. الدليل الكامل خطوة بخطوة: **`docs/DEPLOY_RAILWAY.md`**.

1. Railway → **New Project** → **Deploy from GitHub repo**، اربط المستودع، فرع `main`. البناء عبر `Dockerfile` والضبط عبر `railway.json` (فحص صحة على `/health`) — تلقائيان.
2. أضف **Volume** مركّبًا على `/data` واضبط `SILK_DB=/data/silk.db` و`SILK_USAGE_DB=/data/usage.db` (لا تركّب القرص فوق `data/` — يحوي ملفات CSV مرجعية).
3. **Settings → Networking → Generate Domain**، افتح الرابط → **تظهر الواجهة مباشرةً**. اترك حقل «رابط الباك-إند» فارغًا (نفس الخدمة) → اكتب المنتج → حلّل.
4. تحقّق من `/<الرابط>/health` → `{"status":"ok"}`.

> بديل اختياري: نشر الواجهة وحدها على Netlify (`netlify.toml`, `publish = web`) ووضع رابط الـ API في الحقل؛ حينها فعّل `CORS_ORIGINS` بدومين Netlify (CORS مهيّأ في `api.py`).

---

## مهارة ponytail المثبّتة · Installed skill

المشروع مهيّأ لتفعيل إضافة **[ponytail](https://github.com/DietrichGebert/ponytail)** تلقائياً
عبر `.claude/settings.json` (تُسجّل السوق وتفعّل `ponytail@ponytail`). تشجّع على أقل كود ممكن
(YAGNI، المكتبة القياسية أولاً). عند فتح المشروع في Claude Code قد يُطلب منك الموافقة على تثبيتها،
أو ثبّتها يدوياً:

```
/plugin marketplace add DietrichGebert/ponytail
/plugin install ponytail@ponytail
```

أوامرها: `/ponytail-review` · `/ponytail-audit` · `/ponytail-debt` · `/ponytail-gain` · `/ponytail-help`.

---

## الحالة · Status

**مُنجَز:** النواة (طبقة بيانات + مُصنّف HS + وكلاء + مُرتّب + محرّك) + طبقات Google Trends،
الرسوم الجمركية (WITS)، FAOSTAT، فحوص الجودة، تخزين SQLite، وذاكرة تخزين مؤقت + واجهتا Streamlit
و**FastAPI** + تعبئة Docker وتكامل مستمر (CI) + حراسة الموجة ٠ (مصادقة/سقف/عزل حقن/CORS). اختبارات الدخان الهيرمتيكية: **87** تمر كاملة عبر CI (العدّ الحي في `tests/`).

**خطوات لاحقة مقترحة:** اختبار حيّ شامل ببيانات الإنترنت، توسيع `hs_codes.csv` للقائمة الكاملة عبر
`tools/fetch_hs_codes.py`، لفّ الوكلاء بـ CrewAI، ودمج المصادر المدفوعة (Volza/explee) للأسواق الناجية
من التصفية الأولية فقط.

---

## الرؤية المعمارية · Architecture vision

خارطة التطوير بعد V3 موثّقة في **[`docs/VISION.md`](docs/VISION.md)** — محرّك التقاطع
(Correlation Engine)، دروس "لو أُعيد البناء" (المعمارية الأنحف)، تصميم المخرجات الموحّد،
محرّك اكتشاف الفرص المعكوس، وترقية طبقة الامتثال لقوائم تحقق تنفيذية.

The post-V3 roadmap lives in **[`docs/VISION.md`](docs/VISION.md)**: the Correlation Engine,
"if rebuilt" leaner-architecture lessons, a unified output template, the reverse
opportunity-discovery engine, and the compliance layer upgraded to executable checklists.

## الخطوط على النشر — self-hosted fonts (deploy step)

الواجهة تحمّل خطوط IBM Plex Sans Arabic وMarkazi Text وIBM Plex Mono من
Google Fonts CDN. للاستضافة الذاتية (أداء وخصوصية أفضل): نزّل ملفات woff2
من fonts.google.com على جهاز متصل، ضعها في `web/fonts/`، واستبدل وسم
`<link href="https://fonts.googleapis.com/...">` في `web/index.html`
بقواعد `@font-face` محلية. (بيئة التطوير المعزولة تحجب fonts.gstatic،
فلا يمكن تنفيذ التنزيل منها — خطوة نشر يدوية واحدة.)

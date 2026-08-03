# سِلك — المعمارية المرجعية (تدقيق ما بعد الموجة ١١)

> هذا المستند الحالة الفعلية للكود اليوم (commit `8b7e872`، بعد PR هذا
> التدقيق) — وُلِّد بمشي الشيفرة الحيّة سطراً سطراً، لا من ملخّصات تسليم
> سابقة. حيث يختلف عن `CLAUDE.md`/التقارير الأقدم، القسم ٧ («الفروق») يذكر
> ذلك صراحة بمرجع file:line. راجع أيضاً `docs/VISION.md` (الهدف المعماري)
> و`docs/EXECUTION_PLAN.md` (خطة الموجات وقرارات المالك المستقرة).
>
> **تحديث الحوكمة (2026-07-14):** جرد الوحدات (§٢) أُعيد قياسه بعد PRs
> #76–#83، وأُضيف قسم سجل «ما بعد الموجة ١٣» في
> `docs/DEEP_RESEARCH_DECISIONS.md` يغطّي تلك الـPRs (Eurostat، ترقية عمق
> البعثات، مرآة كومتريد، تقرير العميل، منتجات منافِسة + تموضع سعري، محادثة،
> لقطة سريعة) — كانت السجلات تتوقّف عند الموجة ١٣. التقييم الكامل المرجعي:
> `docs/PLATFORM_ANALYSIS.md`.

## ١. مخطّط الطبقات

```
┌─────────────────────────────────────────────────────────────────────┐
│ api.py (1528 سطراً، 25 مساراً) — FastAPI + web/index.html            │
├───────────────────────────────┬───────────────────────────────────────┤
│ المسار القديم — /analyze       │ المسار الجديد — /research (V5)        │
│ (٣٨ سوقاً، ترتيب+تقاطع)         │ (سوق واحد، بحث عميق بـ١٢ بعثة)         │
│                                │                                       │
│ silk_engine.analyze()          │ silk_missions.deep_research()         │
│  ├─ silk_hs_resolver           │  ├─ silk_market_resolver.resolve_market│
│  ├─ silk_market_ranker         │  ├─ run_all_missions (12× مهمة كلود+  │
│  ├─ ResearchManager (silk_     │  │   أدوات، silk_llm_runtime._run_loop)│
│  │   agents: Trade/Economic/   │  ├─ silk_market_analyst.analyze_market│
│  │   Competition + jury)       │  ├─ silk_synthesis.synthesize()       │
│  ├─ طبقات تعميق اختيارية        │  │   (نفس محرّك حكم /analyze)          │
│  │   (with_* flags)            │  ├─ silk_ai_judge.write_reviewed_     │
│  ├─ correlation.py (اختياري،   │  │   report (كاتب + مراجع)             │
│  │   بطاقة منتج)                │  ├─ silk_quality_gate.run_quality_gate │
│  ├─ silk_synthesis.synthesize()│  │   (حتمي، بعد بناء view)             │
│  └─ silk_decision.decide()     │  └─ silk_trace (تتبّع كل نداء/جولة)     │
│      (طبقة إضافية اختيارية،    │                                       │
│      §٧ الفرق ٣)                │                                       │
├───────────────────────────────┴───────────────────────────────────────┤
│ silk_render.build_view() — القالب الموحّد الوحيد (كلا المسارين)        │
├─────────────────────────────────────────────────────────────────────┤
│ silk_reports.py (render_docx/render_brief) · web/index.html · silk_evals │
├─────────────────────────────────────────────────────────────────────┤
│ silk_storage/silk_store (SQLite) · silk_cache · silk_usage · silk_context│
├─────────────────────────────────────────────────────────────────────┤
│ silk_llm_provider.AnthropicProvider — المزوّد الوحيد خلف واجهة LLMProvider│
├─────────────────────────────────────────────────────────────────────┤
│ طبقة البيانات الحقيقية: silk_data_layer(_v2) · silk_seed_data ·          │
│ CSVs (data/*.csv) · وكلاء المصادر (comtrade/worldbank/trends/…)          │
└─────────────────────────────────────────────────────────────────────┘
```

## ٢. جرد الوحدات — أرقام حقيقية

قياسات مباشرة من الشيفرة الحيّة (`wc -l`, `pytest --collect-only`, فحص
`AGENT_CATALOG`)، لا تقديرات. **مُحدَّثة في تحديث الحوكمة بعد PRs #76–#83**
(2026-07-14) — الأرقام أدناه معاد قياسها على `main` وقتها؛ القيم القديمة
(تدقيق ما بعد الموجة ١١) مذكورة بين قوسين حيث تغيّرت:

| المقياس | الرقم | المصدر |
|---|---|---|
| ملفات بايثون في الجذر | 52 (كان 62) | `ls *.py` |
| إجمالي أسطر بايثون (الجذر فقط) | 20,146 (كان 16,702) | `wc -l *.py` |
| أكبر خمسة ملفات | `silk_reports.py` (2572)، `api.py` (1528)، `silk_research.py` (1367)، `silk_render.py` (1215)، `silk_llm_runtime.py` (1083) | `wc -l` |
| `silk_ai_judge.py` | 1080 سطراً (كان 783) | `wc -l` |
| اختبارات (ملفات) | 92 (كان 74) | `ls tests/*.py` |
| اختبارات (حالات فردية) | 880 (كان 626) | `grep -rh 'def test_' tests/` |
| مسارات API | 25 (كان 21) | `grep -c "@app\." api.py` |
| فئات ترث `BaseAgent` | 18 (كان يُذكر 15 في `CLAUDE.md`) | `grep 'class.*(BaseAgent)' silk_*.py` |
| صفوف AGENT_CATALOG الفعلية وقت التشغيل | 28 (14 أساسية + 12 بعثة V5 + 2 كاتب/مراجع) | `silk_agents.AGENT_CATALOG` بعد استيراد `silk_missions`/`silk_ai_judge` |
| بعثات `/research` (V5) | 12 | `silk_missions.MISSION_ORDER` |
| مراجع CSV وصفوفها | `hs_reference.csv` (6941)، `hs_codes.csv` (5628)، `demographics_l1.csv` (253)، `countries.csv` (251)، `worldbank_seed.csv` (266)، `ports_l1.csv` (235)، `agreements_l1.csv` (87)، `muslim_share.csv` (50)، `requirements_l1.csv` (16)، `backtest_cases.csv` (5 صفوف بيانات) | `wc -l data/*.csv` |
| أدوات CLI (`tools/`) | 10 (`backtest.py`, `dev_console.py`, `fetch_*` ×4, `gen_research_sample.py`, `import_legacy.py`, `refresh.py`, `stage2c_proof.py`) | `ls tools/` |

### مسارات API الـ21

`GET /health`، `GET /resolve/{name}`، `GET /index`، `GET /markets`،
`POST /analyze`، `GET/POST /settings/agents`، `POST /settings/keys`،
`POST /deepen`، `POST /research`، `POST /discover`، `POST /trend`،
`GET /diagnostics`، `GET /sources`، `GET /analyses`، `GET /analyses/{id}`،
`GET /analyses/{id}/brief`، `GET /analyses/{id}/report.docx`،
`GET /analyses/{id}/report.md`، `POST /analyses/{id}/ask`،
`PATCH /analyses/{id}/outcome` (`api.py:262-1129`).

### وكلاء AGENT_CATALOG (المفتاح · الاسم · مدفوع؟ · الأدوات)

الأربعة عشر الأساسية (`silk_agents.py:43-73`، مجانية جميعاً عدا الثلاثة
الأخيرة): `trade`، `economic`، `competition`، `regulatory`، `risk`،
`trends`، `maps`، `channels`، `consumer`، `dynamics`، `synthesis`
(مجانية) — `pricing`، `importers`، `contacts` (**مدفوعة**، بوابة
`/deepen` البنيوية). الاثنا عشر بعثة V5 (`silk_missions.py:46-209`،
مسجَّلة عبر `register_agents`، مجانية جميعاً): `pricing_scout`،
`consumer_culture`، `trade_flow`، `demographics_economy`، `competitors`،
`customs_requirements`، `tariffs_agreements`، `logistics`،
`channels_importers`، `demand_trends`، `risk_news`، `opportunity_gaps`.
صفّان إضافيان (`silk_ai_judge.py:766-777`): `reviewer`، `report_writer`.

كل بعثة V5 تُغلَّف عبر `LLMMissionAgent` (`silk_llm_runtime.py:797-824`) —
أدوات كل مهمة محدودة بـ`allowed_tools` الخاص بها من سجل `TOOLS`
(`silk_llm_runtime.py:47-434`): `comtrade_imports`، `comtrade_competitors`،
`worldbank_indicator`، `wits_tariff`، `trends_interest`، `faostat_supply`،
`web_search`، `gdelt_news`، `openalex_search`، `channels_importers`،
`lookup_reference` (11 أداة).

## ٣. جدول التحقق من الثوابت الثمانية

| # | الثابت | يصمد؟ | نقطة الإنفاذ (file:line) | اختبار الحارس |
|---|---|---|---|---|
| 1 | DataPoint-or-nothing في build_view | **نعم** | `silk_data_layer.py` (تعريف `DataPoint`)؛ `silk_render.py:658-665` (`_dp`، بناء `components_detail`)؛ `silk_render.py:328-343` (`_provenance`) | `tests/test_wave5c_reports.py::test_view_carries_source_line_per_number` |
| 2 | إسقاط الادّعاء بلا استشهاد | **نعم** (مسارين مستقلَّين) | القديم: `silk_research.py:76-84` (`Finding._doctrine`) + `silk_research.py:274-306`؛ الجديد: `silk_llm_runtime.py:535-547` (`_parse_output`، يُسقط بند بمعرّف غائب مع تحذير) | `tests/test_stage3_research.py::test_invalid_finding_downgraded_to_logged_gap_not_swallowed`؛ `tests/test_wave6_llm_runtime.py::test_uncited_finding_is_dropped_and_logged` |
| 3 | مسار حكم واحد | **نعم، بدقّة إضافية موثَّقة** — `synthesize()` (`silk_synthesis.py`) هو مصدر الحكم؛ عند وجود `silk_decision.decide()` (محرّك §8 الموزون) يُظهره `build_view` **وحده** كـ«الحكم الوحيد» ويُحوَّل حكم الجورية إلى سطر كفاية بيانات بلا كلمة حكم (`silk_render.py:629-646`، تعليق «إصلاح مراجعة Stage 5» صريح) | `tests/test_stage5_review_fixes.py::test_single_authoritative_verdict_everywhere` |
| 4 | قالب عرض واحد | **نعم** | `silk_render.py:621-745` (`build_view`) يُستدعى من `/analyze` (`api.py:711`) و`/research` (`api.py:860`) عبر نفس `_view()`؛ فرع `/research` الإضافي `_deep_research_view` (`silk_render.py:555-618`) يُدمَج داخل نفس `view`، لا مسار موازٍ | لا اختبار حارس مباشر باسم «قالب واحد» — الفحص عبر `test_wave6_deep_research_view.py` (يتحقق من مفاتيح `view["deep_research"]`) |
| 5 | عزل `_isolate` لكل نص خارجي | **كان جزئياً — أُصلح في هذا الـPR** | الثغرة: `silk_llm_runtime.py` (سطر ~713-716 سابقاً) كان يعزل `note` فقط من حمولة نتيجة الأداة، تاركاً `value`/`source` خاماً — نص بحث ويب/أعمال بالاسم يصل كلود بلا عزل. **الإصلاح**: `_isolate_external()` جديدة (`silk_llm_runtime.py`) تعزل `value`/`source` أيضاً (أرقام صرفة تُستثنى عمداً) | `tests/test_wave6_llm_runtime.py::test_external_tool_text_isolated_before_reaching_claude` — الاختبار نفسه صُحِّح ليتحقق من عزل حقل `value` المحقون فعلياً (كان يتحقق من وجود الوسمين في أي مكان بالحمولة، فينجح زوراً عبر حقل `note` غير ذي الصلة) |
| 6 | حزمة اختبار هيرمتية | **نعم** | `tests/conftest.py:15-30` (`block_network`، `socket.socket` monkeypatch)؛ بديل `patch("requests.get"/"requests.post", side_effect=OSError(...))` لاختبارات `TestClient` | `tests/test_smoke.py::test_resolver_real_hs_codes` (يتحقق `value is None`)؛ نسخ محلية مكرَّرة في عدة ملفات (فجوة تنظيف معلنة، «M9» في CLAUDE.md، غير حرجة) |
| 7 | بوابة PAID | **نعم** | `silk_agents.py:157-163` (`BaseAgent.run`، الفحص قبل `_execute` — لا نداء يُحاوَل)؛ `silk_context.py` (`deepen_active`/`deepen_context`)؛ `PAID=True` حصراً على `silk_localprice_agent.py`، `silk_volza_agent.py`، `silk_explee_agent.py` | `tests/test_wave2_structure.py::test_paid_agent_structurally_impossible_outside_deepen`، `::test_analyze_endpoint_cannot_activate_paid_layers` |
| 8 | فشل صاخب (409/فجوات معلنة) | **نعم** | `api.py:766-772` (409 عند عدم الجهوزية بلا `allow_degraded`)؛ `_research_readiness()` (`api.py:504-532`)؛ عند `allow_degraded=true` يُعلَن `result["degraded"]`/`degraded_reason` ويُطبَع في كل مشتق (`silk_render.py:718-719`، `silk_reports.py:48-59`) | `tests/test_wave6_research_api.py::test_no_key_returns_409_never_a_silent_skeleton` |

## ٤. تتبّع مسار `/research` (خطوة بخطوة، مع الملفات)

1. **الدخول**: `ResearchRequest` (`api.py:714-733`) → `@app.post("/research")`
   (`api.py:734`) → `_require_key`/`_rate_limit` (`api.py:754-755`).
2. **الحلّ**: `silk_market_resolver.resolve_market(req.market)`
   (`api.py:756-757`) — مطابقة صارمة ثم غامضة (`difflib`)؛ فشل ضعيف = 422 مع
   اقتراحات، لا تخمين. بوابة جهوزية `_research_readiness()`
   (`api.py:504-532`): مفتاح Anthropic + عدم وجود مفتاح مدفوع بلا حماية +
   `silk_ai_judge.available()` + سقف يومي غير مستنفَد؛ فشلها بلا
   `allow_degraded` = **409** (`api.py:766-772`). حلّ HS عبر
   `silk_hs_resolver.resolve()` (`api.py:776-779`) — `None` يصبح `hs_note`
   معلناً.
3. **البعثات**: `silk_missions.deep_research()` (`silk_missions.py:343-391`)
   يفتح `silk_trace.trace_context` ثم `run_all_missions()`
   (`silk_missions.py:285-340`). البعثات الإحدى عشرة (عدا `opportunity_gaps`)
   تعمل **بالتوازي** عبر `ThreadPoolExecutor` مع `contextvars.copy_context()`
   الصريح لكل خيط (`silk_missions.py:320-333` — تعليق يشرح لماذا
   `ThreadPoolExecutor` لا يرث contextvars تلقائياً، خلافاً لـ`asyncio`).
   `opportunity_gaps` تعمل أخيراً وتقرأ نتائج الإحدى عشرة الأخرى فقط
   (`silk_missions.py:335-339`). ميزانية كل بعثة:
   `tool_calls=5`/`max_output_tokens=4000` افتراضياً
   (`_MISSION_BUDGET`، `SILK_MISSION_TOOL_CALLS`/`SILK_MISSION_MAX_TOKENS`)،
   أعمق (`tool_calls=9`) للست الزاوية-كثيفة
   (`_DEEP_RESEARCH_MISSION_BUDGET`)؛ مهلة `SILK_MISSION_TIMEOUT_S=90`
   لكل بعثة (`silk_missions.py:249`).
4. **حلقة الأداة**: كل بعثة تمر عبر `LLMMissionAgent` →
   `run_llm_agent()` → `_run_loop()` (`silk_llm_runtime.py:562-736`).
   `max_rounds = tool_budget + 2`؛ كل جولة تنادي
   `silk_ai_judge._call_tools` (الآن مفوَّضة إلى
   `silk_llm_provider.get_provider().complete_tools`، §٧.٣)؛ نتائج الأداة
   تُسجَّل بمعرّفات `dpN` في سجل الجلسة، وأي بند نهائي يستشهد بمعرّف غائب
   يُسقَط (الثابت #٢)؛ حمولة كل رمز أداة تُعزل بالكامل (الثابت #٥، بعد
   إصلاح هذا الـPR). سقف كلّي عبر التحليل بأكمله
   (`SILK_RESEARCH_MAX_LLM_CALLS=40`/`SILK_RESEARCH_MAX_TOOL_CALLS=100`)
   يُقرأ حيّاً من `silk_context.data_counter()` (`silk_llm_runtime.py:646-656`).
5. **المحلل**: `silk_market_analyst.analyze_market()`
   (`silk_market_analyst.py:91-146`، `api.py:814-816`) — يستهلك تقارير
   البعثات الاثنتي عشرة فقط (+ سياق سردي غير قابل للاستشهاد من بطاقة
   المنتج)؛ نداء `LLMMissionAgent` بلا أدوات (`allowed_tools=[]`) يُنتج
   خمس فئات إلزامية: `demand`/`entry_cost`/`price_competitiveness`/
   `entry_door`/`swot` (`silk_market_analyst.py:29-38`).
6. **التوليف**: `silk_synthesis.synthesize()` (`api.py:818-821`) — المرحلة
   ١ (`JuryCommittee` الحتمية) ثم المرحلة ٢ (حكم كلود المعزول، يستهلك تقييم
   المحلل كسياق JSON معزول). **نقطة الحكم الوحيدة** لكلا المسارين.
7. **الكاتب/المراجع**: `silk_ai_judge.write_reviewed_report()`
   (`silk_ai_judge.py:735-763`، `api.py:822-825`) — يقود `deep_report()`
   (الكاتب، `_MODEL`/Opus، بنية ١١ قسماً إلزامية `_REPORT_SECTIONS`) و
   `review_report()` (المراجع، `_FAST_MODEL`/Haiku — تدرّج تكلفة قائم فعلاً،
   §٧.٤) حتى موافقة أو استنفاد `max_cycles=2`.
8. **بوابة الجودة**: `silk_quality_gate.run_quality_gate(result["view"])`
   (`api.py:862-876`) — **بعد** بناء `view`، حتمية بالكامل (صفر نداء
   كلود/شبكة) — تدقيق تسرّب Markdown/JSON خام، أرقام ثقة خام في السرد،
   بتر منتصف كلمة، بنية الأقسام (يعيد استخدام `_section_order_issues`
   من §٧)، صحة البعثات. **ليست حلقة إعادة كتابة** — نتائجها تُرفَق
   بـ`view["deep_research"]["quality_gate"]` ولا تُوقف التسليم أبداً
   (ملفوفة بـ`try/except`).
9. **العرض/الحفظ**: نفس `silk_render.build_view()` القانوني لكلا
   المسارين (الثابت #٤)؛ الحفظ عبر `silk_storage.save_analysis` إن
   `req.persist` (`api.py:878-884`)، ملفوف بأمان.
10. **التقييم**: `silk_evals.py` أداة **مستقلة غير مربوطة** بمسار
    `/research` الحي — لا `api.py` ولا `silk_quality_gate.py` يستوردانها؛
    تُشغَّل يدوياً (`python3 silk_evals.py --case <key>`) وتتطلب شبكة
    ومفتاح Anthropic فعليَّين، فهي غير قابلة للتشغيل في CI/هذه البيئة
    بتصميمها المُعلَن.

### الميزانيات/المهل/انتشار السياق — كل نقطة تحكّم

| الضابط | القيمة/متغيّر البيئة | الموضع |
|---|---|---|
| نداءات أداة لكل بعثة | 5 (9 للست العميقة) | `SILK_MISSION_TOOL_CALLS`/`SILK_DEEP_MISSION_TOOL_CALLS`، `silk_missions.py:225-246` |
| رموز مخرَج لكل بعثة | 4000 | `SILK_MISSION_MAX_TOKENS`، `silk_missions.py:227` |
| مهلة كل بعثة | 90 ثانية | `SILK_MISSION_TIMEOUT_S`، `silk_missions.py:249,325` |
| أقصى جولات تلقائي/أداة | `tool_budget + 2` | `silk_llm_runtime.py:630` |
| سقف كلّي (كل التحليل) | 40 نداء كلود / 100 نداء أداة | `SILK_RESEARCH_MAX_LLM_CALLS`/`_MAX_TOOL_CALLS`، `silk_llm_runtime.py:646-656` |
| انتشار السياق | `contextvars` (`agent_prefs_context`، `begin_data_counter`، `trace_context`) مُعاد نسخه صراحة لكل خيط متوازٍ | `silk_missions.py:320-321` |
| مهلة الوكيل القديم (٨-الوكلاء) | 45 ثانية (`DEFAULT_TIMEOUT`) — تخصّ `ResearchAgent`/`ResearchManager` القديم لا `/research` | `silk_research.py:46` |

## ٥. الفروق (ما اختلف عن التقرير الخارجي/التوثيق الأقدم)

1. **CLAUDE.md لا يوثّق مسار `/research` (V5) إطلاقاً.** الملف يشرح
   `/analyze` وموجات 0-5 بتفصيل، لكن `/research` (١٢ بعثة كلود بأدوات،
   المحلل، الكاتب/المراجع، بوابة الجودة، التتبّع، حصاد التقييم) — كل ذلك
   من موجات لاحقة (V5 Waves 1-11) — غائب كلياً. هذا القسم (٤) يسدّ الفجوة.
2. **«حكم واحد» يحتاج توضيحاً لا تصحيحاً.** الفهم الأول من قراءة الكود
   السريعة (انظر §٣ رقم ٣) قد يُخطئ فيظن أن `silk_decision.py` يخالف
   الثابت — لكن `silk_render.py:629-646` يطبّق أسبقية صريحة (حكم واحد
   يُعرَض دوماً)، وموجودة اختباراً حارساً مخصَّصاً
   (`test_single_authoritative_verdict_everywhere`) من إصلاح مراجعة سابق
   (Stage 5). لا خلل هنا، لكن التوثيق («الوحيد» في CLAUDE.md) لا يذكر
   `silk_decision.py` بالاسم، فيبدو تناقضاً لقارئ الكود دون هذا السياق.
3. **ثغرة عزل حقيقية في `silk_llm_runtime.py` — أُصلحت في هذا الـPR** (تفصيل
   في §٣ رقم ٥). الاختبار القديم كان يعطي طمأنينة زائفة (يتحقق من وجود
   وسمَي العزل في الحمولة كاملة، لا في الحقل المصاب تحديداً).
4. **جوهر "تدرّج التكلفة" (دَين ٤) كان منجَزاً فعلياً قبل هذا التدقيق.**
   المراجع (`review_report`) وحَكَم evals كانا يستخدمان `_FAST_MODEL`
   بالفعل؛ بوابة الجودة (`silk_quality_gate.py`) بلا أي نداء كلود أصلاً.
   الجديد في هذا الـPR هو تقدير التكلفة بالدولار (§٧.٤) — لم يكن موجوداً
   إطلاقاً قبل هذا الـPR.
5. **`evals/golden_cases.json` فارغ عمداً — ولا يزال كذلك بعد هذا الـPR،
   وهذا قرار مقصود لا فجوة تنفيذ.** التفصيل الكامل في §٦.
6. **حقل `expected` في مخطط الحالة الذهبية غير مربوط بمنطق التقييم
   الفعلي حالياً.** `silk_evals.evaluate_report()`/`run_case()` لا يقرآن
   `case["expected"]` إطلاقاً — محور الاستشهاد البرمجي يقارن أرقام
   التقرير بأرقام بعثات نفس التشغيلة، لا بقيم "متوقَّعة" مرجعية خارجية.
   هذا فجوة تصميم موثَّقة أصلاً في `silk_evals.py` (تعليق أعلى الملف،
   سطور ١١-١٨) لا اختُرِعت في هذا التدقيق — نُسجِّلها هنا لأنها تفسّر
   لماذا "بناء حالات ذهبية" لن يُفعِّل أي فحص جديد قبل ربط لاحق.

## ٦. دَين ٢ (حالات ذهبية) — لماذا بقي `golden_cases.json` فارغاً

توجيه المهمة افترض أن «أربع تشغيلات حقيقية (ETH، NLD، ESP + عيّنة)»
سجّلت أرقاماً حقيقية موثَّقة يمكن استخراجها. تحقّق مباشر (بحث في
`docs/DEEP_RESEARCH_DECISIONS.md`، ملفات الاختبار، `samples/`،
`data/backtest_cases.csv`) يُظهر أن هذا الافتراض **غير صحيح فعلياً**:

- التشغيلات الخمس المذكورة في `docs/DEEP_RESEARCH_DECISIONS.md:661`
  (ETH، NLD×2، ESP) وثّقت **عيوب أنابيب** (فشل تحليل JSON مُسيَّج،
  WGI فارغ، رموز شركاء خام) لا أرقاماً مرصودة يدوياً بمصدر حيّ.
- `silk_evals.py` نفسه (سطور ٢٠-٢٦) والتوثيق
  (`docs/DEEP_RESEARCH_DECISIONS.md:536-539،833-834`؛
  `docs/EXECUTION_PLAN.md:146-153`) يُصرِّحان مراراً عبر خمس موجات متتالية:
  «هذه البيئة بلا وصول شبكي لمصادر البيانات (Comtrade/WorldBank)، فإضافة
  حالة الآن تعني إما اختلاق أرقام أو فراغاً بمظهر التحقق».
- **تحقّقتُ بنفسي في هذه البيئة** (وليس فقط نقلاً عن التوثيق): محاولة
  اتصال مباشرة بـ`comtradeapi.un.org`/`api.worldbank.org` من هذه الجلسة
  تُرفَض ببوابة الشبكة (`403`، `connect_rejected`) — نفس القيد بالضبط
  الذي وصفته الموجات الخمس السابقة يتكرر هنا حرفياً.
- `samples/analysis_latest.json` يحمل بيانات **موسومة/اصطناعية صراحة**
  (مصادر `example.org`، ملاحظات «hermetic double»/«مخزن الحقائق») —
  غير صالحة كحالة ذهبية «حقيقية» بتعريف المخطط نفسه.
- `data/backtest_cases.csv` يحمل تصريحاً صريحاً في رأسه: «الأرقام نفسها
  تُسحب حيّة وقت التشغيل من المصدر، لا من هذا الملف» — لا حقل `value` ولا
  `source_url` لكل صف، فلا يفي بمخطط `golden_cases.schema.json` مباشرة.

**القرار (متّسق مع خمس قرارات مالك سابقة موثَّقة، ومع المبدأ التأسيسي في
CLAUDE.md — لا اختلاق)**: لم تُضَف أي حالة ذهبية مزيَّفة تحمل تواريخ
تحقّق ومصادر غير مُتحقَّق منها فعلياً في هذه الجلسة. `evals/golden_cases.json`
يبقى `[]` بصدق. أول حالة حقيقية تبقى مؤجَّلة صراحةً لبيئة بمفتاح
Anthropic حيّ **ووصول شبكي فعلي** لمصدر رسمي (Comtrade/World Bank) —
وليست هذه البيئة. هذا مسجَّل بالتفصيل في `docs/DEEP_RESEARCH_DECISIONS.md`.

## ٧. الديون المُغلَقة (الأدلة)

### ٧.١ محور حسابي مدرِك للمعادلات (citation-correctness)

**قبل**: `silk_evals.citation_correctness_score()` كان يفحص فقط أن كل
رقم في نص التقرير يرد **حرفياً** في نص/ملاحظة بند بعثة خام — رقم مشتق
(TAM/SAM/SOM، ناتج ضرب) يُسقَط كاختلاق رغم صحّة مدخلاته.

**بعد** (`silk_evals.py`، دالة `formula_grounded_numbers` الجديدة):
يفحص معادلات صريحة (`أ (×|÷|+|-) ب = جـ`، مع نِسَب مئوية) حسابياً؛ رقم
مشتق يُقبَل فقط إن (أ) صحّت المعادلة حسابياً و(ب) طرف واحد على الأقل
مسنَد فعلاً لبعثة حقيقية (مباشرة أو عبر سلسلة معادلات سابقة) — سلسلة
افتراضات كاملة بلا أي رقم حقيقي **تُرفَض** (يمنع تبييض اختلاق عبر معادلة
وهمية). حصة/افتراض مُعلَن صراحة بجوار معادلة صحيحة يُستثنى أيضاً من
الاختلاق (لا يحتاج استشهاداً خارجياً — هو افتراض الكاتب المُعلَن).
اختُبِر بعيّنة إسبانيا (TAM = واردات إسبانيا الحقيقية من التمور،
SAM/SOM بمعادلات صريحة) — `tests/test_wave12_architecture_audit.py`
(4 اختبارات: قبول TAM/SAM/SOM صحيحة، رفض ناتج مختلَق، رفض سلسلة بلا
رقم حقيقي، استدعاء الدالة مباشرة).

### ٧.٢ حالات ذهبية إلى ٥ — لم يُغلَق (انظر §٦)

### ٧.٣ محوّل مزوّد رقيق (`silk_llm_provider.py`، جديد)

استُخرِجت آلية HTTP الفعلية (المسار، رأس الإصدار، شكل الحمولة، استخراج
النص/التعامل مع الرفض) من `silk_ai_judge._call`/`_call_tools` إلى واجهة
`LLMProvider` (`complete`/`complete_tools`) مع `AnthropicProvider` كتنفيذ
وحيد، واختيار عبر `SILK_LLM_PROVIDER` (افتراضي `anthropic`). `_call`/
`_call_tools` أصبحتا واجهتين ثابتتين تفوِّضان للمزوّد بعد فحص السياسة
(`ai_extras_blocked`) — **صفر تغيّر سلوكي**: نفس المسار، نفس الحمولة،
نفس معالجة الفشل/الرفض، مثبَت بالحزمة الخضراء بلا تعديل (626 اختباراً).
14 اختباراً جديداً (`tests/test_wave12_architecture_audit.py`) تغطي:
الاختيار الافتراضي/الاحتياطي/المفرد المخزَّن، غياب المفتاح، تفويض
`_call`/`_call_tools` بنفس الوسائط والنتيجة، بقاء حجب `ai_extras` في
`silk_ai_judge` (سياسة) لا `silk_llm_provider` (آلية)، ومطابقة سلوك
النجاح/الرفض السابق حرفياً.

### ٧.٤ تدرّج التكلفة + تقدير الدولار

**تدرّج النموذج**: تحقَّق أنه **كان منجَزاً بالفعل** قبل هذا الـPR —
`review_report` (المراجع) على `_FAST_MODEL` (`silk_ai_judge.py:722`)،
حَكَم `silk_evals` على `_FAST_MODEL` (`silk_evals.py`)، وبوابة الجودة
بلا أي نداء كلود (`silk_quality_gate.py`، تحقَّق ببحث نصّي — لا
`_call`/`_MODEL` في الملف). أُضيف اختبار حارس انحدار
(`test_reviewer_already_uses_fast_model_regression_guard`،
`test_quality_gate_makes_zero_llm_calls`) لتثبيت هذا صراحة.

**الجديد**: تقدير تكلفة بالدولار لكل تشغيلة — `silk_pricing.py` (وحدة
جديدة، مصدر التسعير الوحيد: Opus $5/$25 لكل مليون رمز إدخال/إخراج،
Haiku $1/$5، من توثيق Anthropic الرسمي)؛ `silk_context.record_llm_usage()`
(قناة جانبية صامتة جديدة تراكم رموز الإدخال/الإخراج لكل نموذج داخل عدّاد
`data_economics` القائم)؛ `silk_llm_provider.AnthropicProvider` يستدعيها
بعد كل رد ناجح يحمل `usage`. النتيجة تظهر في
`result["data_economics"]["cost_usd_estimate"]`/`cost_usd_by_model`
لكلا المسارين (`/analyze` عبر `silk_engine._economics`، `/research` عبر
`api.py`) — نموذج غير مُسعَّر يُستبعد من المجموع ويُعلَن في
`cost_unpriced_models`، لا يُخمَّن سعره. 9 اختبارات جديدة تغطي التسعير
والتراكم والتسجيل عبر المزوّد ودمج المحرّك.

### ٧.٥ تقسيم الوحدة (`silk_ai_judge.py`) — لم يُنفَّذ، والسبب

**التقييم**: `silk_ai_judge.py` 783 سطراً بعد استخراج §٧.٣ (كان 816) —
**ليس كبيراً استثنائياً** مقارنةً بمعايير هذا المستودع نفسه (`silk_reports.py`
1908، `silk_research.py` 1367، `api.py` 1160، `silk_llm_runtime.py` 838،
`silk_render.py` 865 — خمسة ملفات أكبر منه فعلاً). قسم الكاتب/المراجع
(§الطبقة ٤، الأسطر 515-783) نقطة انقسام طبيعية نظيفة (~270 سطراً).

**سبب التخطّي**: 16 ملف اختبار يستوردون من `silk_ai_judge` مباشرة، وعدد
منها (`test_wave6_report_writer.py` وغيره) يُطعِّم (`patch`)
`"silk_ai_judge._call"` بينما يستدعي `deep_report`/`review_report` —
أي انقسام يستخدم `from silk_ai_judge import _call` (استيراد اسم مباشر
في `silk_writer.py` الجديد) سيُبطل هذا التطعيم صامتاً (الاسم يُربَط
بكائن الدالة الأصلي وقت الاستيراد، لا يُعاد تفكيكه عند تطعيم
`silk_ai_judge._call` لاحقاً) — يتطلب إعادة كتابة كل موضع نداء داخلي
(`_call`→`silk_ai_judge._call`، وكذلك `_isolate`/`_facts`/`_PRINCIPLE`/
`_FAST_MODEL`/`available`/`_user_steer`/`_extract_json`/`_MODEL`) عبر
~270 سطراً، بمخاطرة انحدار حقيقية (سطر واحد منسي = اختبار هيرمتي يفشل
بصمت بنداء شبكة حقيقي محجوب). **القرار**: التخطّي — الاستفادة (تنظيم
معماري) لا تبرِّر مخاطرة التغيير الميكانيكي الكثيف عبر 16 ملف اختبار،
خصوصاً أن الحجم ليس شذوذاً معمارياً أصلاً. مسجَّل هنا وفي
`docs/DEEP_RESEARCH_DECISIONS.md` كما طلب التوجيه صراحة.

## ٨. الإصلاحات البنيوية المرافقة لهذا التدقيق

- **`silk_llm_runtime.py`**: عزل `value`/`source` في حمولة نتيجة الأداة
  (الثابت #٥، الفجوة الحقيقية الوحيدة المكتشَفة بين الثوابت الثمانية).
- **`tests/test_wave6_llm_runtime.py`**: تصحيح
  `test_external_tool_text_isolated_before_reaching_claude` ليتحقق من
  عزل حقل `value` المحقون تحديداً، لا من وجود وسمَي العزل في أي مكان
  بالحمولة (كان ينجح زوراً عبر حقل `note` غير المصاب).

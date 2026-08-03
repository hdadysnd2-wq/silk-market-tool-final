# Source-Utilization Audit — تدقيق استغلال المصادر (Stage 1A)

> **Snapshot note (added 2026-07-14).** §1–§4 are the **Stage-1** state; §5 (AFTER)
> and later PRs resolved most gaps. Do NOT read §1–§4 as current — the "WGI/LPI/FX
> collected but never read" gap in particular is **RESOLVED** (annotated inline below;
> the consumer is `silk_engine._enrich_risk` + the `with_research` RiskAgent, guard-tested).
> Same discipline as `docs/AUDIT_STATUS.md`: read for method, verify claims against
> current code. Current full reference: `docs/PLATFORM_ANALYSIS.md`.

**Method:** static call-site trace of every configured source through `analyze → ranker → agents → synthesis → view/report`, gates traced through `api.AnalyzeRequest` defaults and `web/index.html buildBody()` — plus **three instrumented end-to-end runs** (per-host HTTP attempt counters wrapped around both `requests.*` and the pooled session): default `/analyze` (dates→CHN), all-free-flags (dates→CHN), all-free-flags (honey→DEU). Sandbox note: external data hosts are policy-blocked here (403) — attempts and short-circuits are still fully measurable; production behavior noted per source.

## 1. The call-site truth table

| Source | Call site | Gate | Default POST /analyze? | UI no-keys? | Should feed | Root cause if dark |
|---|---|---|---|---|---|---|
| UN Comtrade | ranker `_gather_row`→`market_imports_cached` (silk_market_ranker.py:140); TradeFlow/Competition agents (silk_agents.py:107-187); trend (silk_engine.py:147) | none (core) | **YES** | **YES** | market size, competitors, trend | used (keyless throttling is the production limiter) |
| World Bank | ranker income/population (silk_market_ranker.py:143-148); EconomicAgent | none (core) | **YES** | **YES** | demand (income/PPP/pop) | used |
| FAOSTAT | `_enrich_faostat` (silk_engine.py:124,248) | `with_faostat`; UI derives `!!S.keys.FAOSTAT` | NO | NO | consumer/demand | **UI gating-model bug** — free keyless source gated behind a nonexistent "FAOSTAT key" box (index.html:599) |
| WITS tariffs | `_enrich_tariffs` (silk_engine.py:122,234) | `with_tariffs`; UI `!!S.keys.WITS` | NO | NO | regulatory/pricing | **UI gating-model bug** — same nonexistent-key pattern (index.html:598); engine wiring complete & correct |
| Google Trends | `_enrich_trends` (silk_engine.py:120,221) | `with_trends`; UI toggle, default off | NO | NO | demand (search interest) | flag-never-set (toggle defaults off) |
| Google Maps | `_enrich_maps` (silk_engine.py:126,262) | `with_maps` + key | NO | NO | competitors (named businesses) | flag default-off + key-not-passed |
| Serper | top-level culture `_websearch` (silk_engine.py:186,372) + inside NamedCompetitors/Importers/Channels agents | `with_websearch` / `with_competitors` (UI forces competitors ON) | NO | **attempted via competitors, degrades to tagged-None** (silk_websearch_agent.py:48-52) | culture + named competitors | key-not-passed (server env), `with_importers/channels` never set by UI |
| L1 requirements CSV | `_enrich_requirements` (silk_engine.py:145,358) — offline | `with_requirements`; UI forces ON | NO | **YES** | regulatory checklist | raw-API default-off only |
| SerpApi prices | `_enrich_localprice` (deepen-only; field absent from AnalyzeRequest) | `/deepen` + key | NO (structural) | NO | pricing | deepen-only by design; **`LOCALPRICE_API_KEY` undocumented in .env.example** |
| Volza / Explee | `_enrich_volza/_explee` (deepen-only) | `/deepen` + keys | NO (structural) | NO | importers/buyers | deepen-only by design |
| Claude | synthesis stage-2 + `ai_report` | `/deepen` + `with_ai` + key | NO (structural) | NO | verdict narrative | deepen-only by design |
| **WGI/LPI/FX (M2)** | **collected** (silk_collectors.py:106) → fact store; ~~no reader anywhere~~ | n/a | NO | NO | Risk section/pillar | ~~missing integration~~ **✅ RESOLVED (Stage 2A, see §5)** — the reader was built: `silk_engine._enrich_risk` (silk_engine.py:316, store-first via `get_indicator`) and the `with_research` RiskAgent (silk_research.py:921) both consume these; the decision pillar reads them via `_pillar_inputs` → `silk_decision._pillar_risk` (silk_decision.py:159). Enabled by default (`with_risk`/`with_research` in the server policy, api.py:474). Guards: `test_stage2a.py::test_risk_reader_serves_real_store_facts_and_fx_volatility` (store-first), `test_stage2a.py::test_source_policy_is_server_decided_and_client_cannot_disable` (policy enables both), `test_risk_pillar_and_logistics.py`, `test_project_review_fixes.py::test_risk_error_path_returns_tagged_datapoint_not_typeerror` |

## 2. Instrumented runs — sources actually hit & facts contributed

| Host / source | default dates→CHN | full-flags dates→CHN | full-flags honey→DEU |
|---|---|---|---|
| comtradeapi.un.org | **8 attempts** (8 fail-403) | 18 (18 fail) | 18 (18 fail) |
| api.worldbank.org | **12 attempts** (12 fail) | 12 (12 fail) | 12 (12 fail) |
| wits.worldbank.org | 0 | 1 (fail) | 1 (fail) |
| faostatservices.fao.org | 0 | 1 (fail) | 1 (fail) |
| google.serper.dev | 0 | **0 — short-circuit "requires SEARCH_API_KEY"** (5 tagged gaps) | 0 (5 gaps) |
| maps.googleapis.com | 0 | **0 — short-circuit on key** (1 gap) | 0 |
| trends (pytrends) | 0 | 0 — lib absent here; production: flag-off | 0 |
| **Facts contributed (value≠None)** | 0 | **3 — all from offline L1 requirements** | **9 — all L1 (EU chain)** |
| Tagged gaps (value=None) | 4 | 14 | 13 |

**Production corroboration (deployed instance screenshot):** Economic agent 37/38 (WB fine keyless) vs Trade agent 2/30 — the Comtrade preview-tier throttling under the 38-market concurrent fan-out, exactly as traced in ANALYSIS.md §3; M2's budgeted serial collector + fact store is the built remedy, pending a `COMTRADE_API_KEY`.

## 3. Verdicts

1. **Only 2 of 12 sources run on a bare `/analyze`** (Comtrade + World Bank). The UI raises that to ~4.5 (adds L1, trend, and a keyless-degrading Serper attempt).
2. **Three free sources are dark for a pure UI-model bug** (FAOSTAT, WITS behind nonexistent key boxes; Trends behind a default-off toggle) — the engine wiring for all three is complete and correct.
3. **Five sections silently show "غير مرصود" because the server key was never consulted** — the UI's localStorage keys panel never transmits anything; flags derived from it are the only trigger.
4. ~~**The M2 risk indicators (WGI/LPI/FX) are collected and never read**~~ — **✅ RESOLVED in Stage 2A**: the consumer was built (`silk_engine._enrich_risk`, silk_engine.py:316) and reads them store-first, plus the decision pillar consumes them via the `with_research` RiskAgent. This line is kept for the historical Stage-1 record; see §5 and the WGI/LPI/FX row in §1 for the resolution anchors and guard tests. (⚠ Anyone re-grading current state from this Stage-1 section: this specific gap is closed.)
5. No source is fabricating; every failure is provenance-tagged (verified in all runs). The failure is **utilization**, not honesty.
6. Doc bug: `LOCALPRICE_API_KEY` missing from `.env.example`.

## 4. Stage-2A implications (the fix list this audit mandates)

- Server-side source policy: agents attempt **all mapped sources unconditionally** when the server env allows; kill key-derived UI flags as the gate.
- Fix the UI gating model (FAOSTAT/WITS/Trends are free — always on; keys panel becomes a read-only server-status view).
- Wire `with_importers`/`with_channels` (currently unreachable from UI).
- ~~Add the WGI/LPI/FX reader (Risk Agent, M3a §4b).~~ **✅ DONE** — `silk_engine._enrich_risk` + the `with_research` RiskAgent (anchors and guard tests in §1).
- Document `LOCALPRICE_API_KEY`.
- Per-section source-coverage score + provenance appendix (2A spec).

---

## 5. AFTER — Stage 2A/2B enforcement (hermetic proof, tools/stage2c_proof.py)

Same two cases re-run behind realistic HTTP doubles (production payload schemas; sandbox blocks live hosts — the identical runner executes live via `--live` on the deployment):

| Metric | BEFORE (Stage 1) | AFTER (Stage 2) |
|---|---|---|
| Sources contributing facts | 1 (L1 only) | **6** (Comtrade، World Bank، Serper، Google Maps، Google Trends، L1) |
| Facts — dates→CHN | 3 | **28** (Serper 15، WB 4، Comtrade 3، L1 3، Maps 2، Trends 1) |
| Facts — honey→DEU | 9 | **34** |
| Data coverage % (header) | 0.0 / 0.0 | **80.0 / 88.0** |
| Sections passing the 2B gate | 0 | **5 لكل حالة** (market_size, regulatory, competitors, demand, risk) |
| Serper/Maps short-circuits | 5+1 لكل تشغيلة | **0** — سياسة الخادم + مفاتيح الخادم |
| WGI/LPI/FX readers | لا قارئ | **row['risk'] فعلي** (بما فيه تقلب FX من السلسلة) |

Every criterion driver from §4's fix list is verified by `tests/test_stage2a.py` + `tests/test_stage2b.py` (142-suite green). Live confirmation: run `python3 tools/stage2c_proof.py --live` on the deployment (needs `SEARCH_API_KEY`, `GOOGLE_MAPS_API_KEY`, `pytrends`, and ideally `COMTRADE_API_KEY`).

---

## 6. Stage 3 توسعة — التثليث (إحصاءات المرآة) لحقائق الجانب السعودي

مراجعة تقرير Stage 5 طلبت التثليث قبل التشغيل الحي — نُفِّذ فوق `saudi_share_pct`
(وكيل `competitor`) و`saudi_border_unit_value_usd_kg` (وكيل `pricing`)، أعمق
حقيقتين تتعلقان بالجانب السعودي مباشرة والأكثر عرضة لفجوة الإبلاغ الرسمية:

- **الأساسي**: تقرير الجهة المستوردة عن السعودية (partner=SAU ضمن صفوف كومتريد
  الحالية — لا نداء جديد).
- **المرآة**: صادرات السعودية المُعلنة مباشرة (`comtrade_trade` بـ
  `reporter=SAU, flow=X` — نداء كومتريد جديد، نفس المصدر، منظور إبلاغ مختلف).
- **القاعدة** (`silk_research._triangulate`، دالة نقية): القيمة المعروضة =
  الأساسية دوماً (لا دمج/متوسط مخترع)؛ عند التوفّر المزدوج يُحسب التباين
  (عتبة 20% كسابقة Stage 2A `xval_note`) — اتفاق يُعلَن دون مساس بالثقة،
  وتباعد يُخفِّض ثقة الأساسية (0.9→0.6) ويُعلَن نصاً؛ توفّر أحدهما فقط = مصدر
  واحد موسوم «غير مثلَّث»؛ غيابهما معاً = فجوة معلنة كسابق عهدها — لا صفر مختلق.
- **السيناريو المُثبَت** (`tests/test_stage3_triangulation.py`، 12 اختباراً):
  غياب السعودية عن تقرير الجهة المستوردة (فجوة بيانات رسمية حقيقية شائعة) —
  التقرير المباشر (مرآة) يستدرك القيمة بمصدر واحد موسوم بدل إسقاط الحقيقة.
- **الظهور في المخرَج**: كلا المصدرين في `sources[]` (يستحيل بنيوياً إخفاء
  التباين)، وسطر الإفصاح (اتفاق/تباين/عدم تثليث) مطبوع في Word وMarkdown
  والواجهة — تحقّق مباشرةً بـ `test_triangulation_disclosure_visible_in_rendered_report`.

المجموعة الكاملة: **182 ناجحاً**.

**قرار المالك (2026-07-06):** المرحلة ١ (تثليث المرآة أعلاه) **مقبولة** —
تقنية سليمة وتنفيذ صادق. لكن التوجيه الأصلي حدَّد **تثليثاً متعدد الإشارات
مُحفَّزاً بالفجوة** (Serper لأسعار التجزئة، Google Maps لكثافة التجزئة،
Google Trends للمسار الزمني) لفجوات حجم السوق/الطلب/التسعير تحديداً — وهذا
**غير مغطّى** بتثليث كومتريد ويبقى **مرحلة ٢ ملزمة غير مُسقَطة**. عيّنة
التقرير الحالية («الأسعار: 0/0»، «الطلب: 1/3») هي بالضبط ما صُمِّمت المرحلة
٢ لسدّه.

## 7. Stage 3 المرحلة ٢ (مُلتزَم بها، مؤجَّلة بعد التشغيل الحي)

**لا تُنفَّذ قبل** تسليم المالك تقرير تمور→الصين الحي وتحديد الفجوات
الباقية فعلياً مع مفاتيح حقيقية — التنفيذ يستهدف الفجوات المُلاحَظة حياً لا
افتراضية.

المواصفة (كما حدَّدها المالك حرفياً):

- **المُحفِّز**: فجوة في مصدر رسمي (كومتريد لحجم السوق، WITS للتعريفة،
  FAOSTAT للطلب، أو غياب تسعير مباشر).
- **الإشارات**: أسعار Serper (`silk_localprice_agent`/`silk_websearch_agent`)،
  كثافة تجزئة Google Maps (`silk_maps_agent`)، مسار Google Trends
  (`silk_trends_agent`) — كلها موجودة أصلاً، صفر تكامل جديد.
- **عقد المخرَج**: أي تقدير مثلَّث `modeled:true` بحقل `formula` صريح +
  قائمة مصادر الإشارات التي غذّته (نفس مخطط `Finding` القائم).
- **سقف الثقة**: 0.5 على أي تقدير متعدد الإشارات — لا يتجاوزه أبداً مهما
  اتفقت الإشارات.
- **أولوية الرقم الرسمي**: عند تعارض >30% مع رقم رسمي موجود، **الرسمي يفوز**
  (التعارض يُعلَن، لا يُخفى ولا يُسقَط الرقم الرسمي صامتاً).
- **حارس الميزانية**: احترام حدود المعدّل/الحصة القائمة على Serper/Maps/Trends
  — لا تفريع غير محكوم.
- **اختباران إلزاميان** قبل اعتبارها منجزة: (١) سيناريو تجويع كومتريد ⇐ تقدير
  مثلَّث (`modeled:true` + `formula` + `sources` + ثقة ≤0.5). (٢) سيناريو
  تجويع كل الإشارات ⇐ فجوة معلنة صادقة، بلا تقدير مختلق.

مُسجَّلة كمهمة #56 في قائمة المهام؛ **بانتظار تسليم التقرير الحي** قبل البدء.

---

## 8. المرحلة ٢ — منفَّذة (بعد تسليم التقرير الحي: دقيق قمح → الإمارات)

**النطاق المُنفَّذ فعلياً** (قرار هندسي واعٍ لتجنّب الاختلاق، مُوثَّق بصدق):

- **حجم السوق (TAM)**: بديل غير دولاري `market_activity_index` (0..1، Google
  Maps كثافة تجزئة + Google Trends اهتمام) — **لا** يُقارَن بدولار TAM
  (وحدتان مختلفتان تماماً؛ اختلاق معامل تحويل $/مؤشر كان سيكون تخميناً غير
  مسنود)؛ يغذّي عمود جاذبية السوق فقط عند غياب `tam_log` كلياً (§8،
  `silk_decision._pillar_market`).
- **النمو (`import_growth_pct`)**: تقدير مثلَّث حقيقي من Google Trends (نمو
  الربع الأول↔الأخير من سلسلة اهتمام واحدة — نفس وحدة % الرسمية، قابل
  للمقارنة والتعارض) عبر `_triangulate_estimate` (رسمي أولاً، تعارض >30%
  الرسمي يفوز ويُعلَن، تقدير محض بثقة مسقوفة 0.5 عند غياب الرسمي).
- **حارس ميزانية حقيقي**: نداء Trends واحد فقط لكل تشغيلة وكيل (يُحاوَل عند
  الفجوة الرسمية فقط، ونتيجته الواحدة تُشارَك بين النمو ومؤشر النشاط معاً —
  `silk_trends_agent.trends_series` الجديدة، لا تكرار نداء pytrends المحدود
  أصلاً، وقد رصدنا 429 حياً بالفعل).
- **مُسقَط من هذا الإصدار عمداً** (تُوثَّق الفجوة لا تُسكَت): استخراج سعر
  تجزئة رقمي آلي من نتائج Serper (عقد المخرَج ذكر "Serper لأسعار التجزئة")
  — تطلّب تطبيع عملة/وزن من عناوين نصية حرة (مثال حي: "Wheat Flour 10kg" ‏—
  استخراج الوزن والعملة تلقائياً منها كان سيعيد بالضبط مخاطرة "استخراج أرقام
  آلي من مقتطفات" التي رفضتها مراجعة Stage 5 صراحةً). التسعير المثلَّث يبقى
  بنداً مؤجّلاً (٢.١) لحين تحديد آلية تطبيع لا تخاطر بالاختلاق.
- **الاختباران الإلزاميان منفَّذان**: `tests/test_stage3_phase2_triangulation.py`
  (٩ اختبارات) — تجويع كومتريد ⇐ تقدير مثلَّث معلن؛ تجويع كل الإشارات ⇐ فجوة
  صادقة صفر اختلاق. المجموعة الكاملة: **201 ناجحاً**.

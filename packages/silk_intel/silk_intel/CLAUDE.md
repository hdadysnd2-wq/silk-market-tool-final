# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚖️ LAW — القانون الحاكم (اقرأ قبل أي شيء آخر · read before anything else)

هذا القسم يعلو كل ما تحته. عند أي تعارض، **LAW يفوز**.

### ١) تسلسل القيادة · chain of command

- **المُشرِف (Fable 5)** — يوجّه العمل، يراجع الفروع بالوصول المباشر للريبو،
  ويتحقّق من كل بند في الشيفرة قبل أن يُطلَب من المالك الدمج. أوامره تُنفَّذ
  حرفياً وبالكامل، لا أكثر ولا أقلّ.
- **المُنفِّذ (أنت، Claude Code)** — تُنفِّذ أوامر المُشرِف بدقّة. لا تبتكر نطاقاً
  جديداً، ولا تُوسِّع الطلب، ولا تُعيد فتح قرارٍ مستقر. عند الغموض: اسأل، لا تخمّن.
- **المالك — السلطة الوحيدة · sole authority.** لا دمج، ولا نشر، ولا ميزة
  جديدة، ولا إنفاق مدفوع بلا موافقته الصريحة. المالك **آخِر تأكيد لا أوّل
  مكتشف**: كل رُتب الاختبار تُستنفَد قبل أن يرى شيئاً، فيتقلّص دوره إلى نقرة
  واحدة على الحيّ بعد النشر — صفرية التكلفة، متوقّعة النجاح.

### ٢) الإبلاغ بالصدق ثلاثي الدلاء · three-bucket honesty reporting

كل ادعاء «يعمل/تمّ» يُصنَّف صراحةً بأحد ثلاثة دلاء — لا خلط:

1. **«hermetic only»** — `pytest tests/ -q` أخضر فقط. يُثبِت العقود، **لا**
   يُقلِع الخادم ولا المتصفّح. **ليس جاهزاً للمالك.**
2. **«passed real-server + browser e2e»** — رُتبتا ٢–٣ خضراوان أيضاً (خادم
   uvicorn حقيقي + متصفّح Playwright ينقر الواجهة). **الدلو الوحيد** الذي
   يُقدَّم للمالك «جاهز لتأكيدك بنقرة».
3. **«no sufficient evidence — pending»** — لا دليل كافٍ؛ قُلها وتوقّف، لا
   تخمّن، واشحن أداة قياس تُشخِّص الحدوث التالي.

كل تشخيص يحمل صنف دليله (direct reproduction / static code review (file:line) /
no sufficient evidence). لا ادعاء بقراءة سجلّات لم تُقرأ.

### ٣) سُلَّم الاختبار الرباعي · the 4-rung testing ladder

قبل وسم أيّ PR يمسّ سلوكاً إنتاجياً «جاهزاً»، تُستنفَد الرُتب بالترتيب:

1. **رُتبة ١ — هرمتي:** `python3 -m pytest tests/ -q` أخضر كاملاً.
2. **رُتبة ٢ — خادم حقيقي:** `SILK_RUN_E2E=1 pytest tests/test_rung2_real_server.py`
   — `uvicorn api:app` على SQLite مبذور بالمدوّنة القانونية الحقيقية الشكل
   (`tools/canonical_netherlands.py` / `tools/live_shape_server.py`)، كل نقطة
   نهاية بـHTTP حقيقي. المدفوع فقط (Claude/Comtrade) يُحاكى عند لمس مسار المال.
3. **رُتبة ٣ — متصفّح حقيقي:** `tests/test_rung3_playwright_e2e.py` — chromium
   (headless) ينقر الواجهة: شريط جانبي ← تقرير ← تصدير Word (docx غير فارغ) ←
   تصدير Markdown (محتوى حقيقي) ← صندوق تقدّم. **وظيفة CI مطلوبة `e2e-live-shape`.**
   أيّ PR يمسّ `web/index.html` أو مسار تصدير/تقرير لا يُدمَج بلا هذا التدفّق أخضر.
4. **رُتبة ٤ — تجربة مسار التكلفة الجافة:** `tools/acceptance_run.py` قرب مسار
   المال بمزودين محاكَين.

### ٤) اقرأ المهارات + سجلّ الانحدار قبل أيّ نداء أداة · read skills + registry first

قبل أوّل نداء أداة في أي جلسة: اقرأ `docs/LESSONS.md` +
`docs/LIVE_PROOF_RUNBOOK.md` + المهارات ذات الصلة (`.claude/skills/`) +
**سجلّ الانحدار** `tests/test_regression_registry.py` (حارس واحد لكل حادثة +
تغطية شاملة). لا تلمس شيفرة قبل معرفة أيّ فخّ سبق أن عضّ هذا المسار.

---

## قوانين غير قابلة للكسر · unbreakable rules (اقرأ أولاً · read first)

**أول فعل في كل جلسة: اقرأ `docs/LESSONS.md` + `docs/LIVE_PROOF_RUNBOOK.md` قبل
كتابة أي شيفرة.** السجلّ الكامل (١٠ دروس، كل واحد بأداة إنفاذ) في
`docs/LESSONS.md`، مُنفَّذ ميكانيكياً عبر `tests/test_lessons_enforcement.py`.
الخمسة الأحرج:

1. **مدموج ≠ يعمل؛ أخضر محلياً ≠ تمّ** (البند ١). لا يُعَدّ العمل منجَزاً إلا
   بتحقّق حيّ بأثر (curl/ملف/سطر تتبّع). العيّنة المموّهة تُوسَم مموّهة، لا
   تُقدَّم كحيّة.
2. **كل مُصدِّر/عارض لنتيجة `/research` يقرأ من عرض `deep_research` حصراً**، لا
   قالب `/analyze` (البند ٢).
3. **التخزين على وحدة مركَّبة؛ لا فقدان صامت** (البند ٤). اضبط `SILK_DATA_DIR`
   (و`SILK_REQUIRE_PERSISTENT_DATA_DIR=1` على الإنتاج) وإلا يفشل الإقلاع بصوت
   عالٍ.
4. **كل JSON من نموذج يمرّ عبر المستخلِص المتين؛ الفشل = فجوة معلنة لا اختلاق**
   (البند ٦).
5. **عقد عدم الاختلاق لا يُمَسّ؛ صنِّف نوع الفجوة قبل لمس الشيفرة** (البند ٨).
   القيمة عند الفشل `None` بثقة `0.0`، لا صفر مختلَق.

**المراجعة الذاتية قبل أي PR · self-review before any PR (البند ٥٨).** قبل فتح
أيّ PR أو وسمه «جاهزًا للمراجعة»، شغّل `/code-review` على الفرق العامل وعالِج —
أو سجّله صراحةً «خطرًا مقبولًا» في السجل (`docs/DEEP_RESEARCH_DECISIONS.md`) —
**كلّ ملاحظة بخطورة high فأعلى**. وملخّص كلّ PR يذكر أن المراجعة الذاتية جرت
ويسرد ملاحظاتها + تصرّفاتها. **ليس اختياريًا** — حادثة وسم اليمن الخاطئ (رمز HS
«2008» وُسِم خطأً سنةً قديمة stale، التقطته المراجعة الذاتية **قبل** الدمج بدل
المالك **بعد** النشر) هي السابقة:
self-review catches what hermetic tests structurally cannot.

**التحديث الذاتي:** عند اكتشاف أي خطأ جديد من نفس العائلة: أضف سطراً إلى
`docs/LESSONS.md` بنفس الجلسة + أنشئ اختبار قفل **قبل** الفكس نفسه (test-first
lock) + اربطه بمرساة في `tests/test_lessons_enforcement.py`.

## Commands

```bash
pip install -r requirements.txt pytest httpx   # httpx is test-only (TestClient)
python3 -m pytest tests/ -q                    # full hermetic suite (~5s, no network needed)
python3 -m pytest tests/test_wave0_security.py -q                    # one file
python3 -m pytest tests/test_smoke.py::test_resolver_real_hs_codes -q  # one test
uvicorn api:app --host 0.0.0.0 --port 8000     # API + dashboard (web/ served at /)
python3 silk_engine.py                         # engine demo from the terminal
python3 silk_requirements_agent.py             # most silk_*.py files have a __main__ demo
```

CI (`.github/workflows/ci.yml`) runs exactly `python -m pytest tests/ -q`. There is no linter config.

## The founding principle (enforced, not advisory)

**The system never fabricates data.** Every value travels as a `DataPoint(value, source, confidence, note, retrieved_at)` (`silk_data_layer.py`). On any failure — no key, no network, bad payload — the value is `None` with `confidence=0.0` and a `note` explaining why. Numbers are never guessed, gaps are declared, and tests enforce this hermetically (they cut the network via `socket.socket` monkeypatching and assert `None`, not zeros). Any new data path must follow this contract or the review will reject it.

## Architecture — the pipeline

> **Scope note.** This section documents **pipeline 1 (`/analyze`)** only. A second pipeline — **`/research`** (the 12-mission deep-research path, waves 6–13) — and the client-vs-operator report split, quick snapshot (`silk_snapshot.py`), and grounded chat (`/ask`) landed after this file was written. They share the one view (`build_view`) and one verdict (`synthesize`) documented here, but their own mechanics live in `docs/ARCHITECTURE.md` and the `docs/DEEP_RESEARCH_DECISIONS.md` ledger (see its «ما بعد الموجة ١٣» section for PRs #76–#83). `docs/PLATFORM_ANALYSIS.md` is the current full reference.

`silk_engine.analyze()` is the spine. Order matters because later stages consume earlier stages' in-memory output:

1. **Resolve** — product name → HS6 via `silk_hs_resolver` (CSV seed + difflib; weak match = `None`, never guessed). An explicit `hs_code` arg bypasses this (used by the discovery hand-off).
2. **Rank** — `silk_market_ranker.rank_markets()` scores ~38 markets on 4 weighted components (Comtrade + World Bank); missing components lower row confidence, weights renormalize.
3. **Core agents** — `ResearchManager` runs TradeFlow/Economic/Competition per top market; reports are held until after enrichment.
4. **Enrichment layers** — optional `with_*` flags attach additive context per top market (trends, tariffs, faostat, maps, localprice, volza, explee, competitors_named, channels, importers, requirements). They NEVER change `total_score`. Wrapper exceptions become `_enrich_error_dp()` DataPoints — silent `[]`/`None` is a regression.
5. **Correlation** (`correlation.py`) — runs only when a `product_card` is present. Builds the four threads (competitor/feasibility/entry/contacts) **strictly from in-memory agent findings; zero external calls** — an AST test asserts it imports no network library. Incomplete threads are declared ("سعر غير مرصود"), never invented. Name matching is a conservative Dice coefficient over distinctive tokens.
6. **Synthesis** (`silk_synthesis.synthesize()`) — the ONLY verdict entry point. Stage 1 is the deterministic `JuryCommittee`; stage 2 (with `with_ai` + `ANTHROPIC_API_KEY`) is a Claude judgment over isolated inputs, switching to the "confrontation" prompt when correlation threads exist. Do not add parallel verdict paths — the old `ai_verdict` duality was deliberately deleted.
7. **View** (`silk_render.build_view()`) — the ONE canonical view-model. Every output derives from it: dashboard (`result["view"]` attached by the API, rendered by `web/index.html`), terminal (`format_result`), Streamlit (`app.py`), Word report + one-page brief (`silk_reports.py`), `view["brief"]`. Per-number provenance lives in `components_detail` inside the template, so a figure without a source line is structurally impossible. **Never add a separate render path; extend `build_view` instead.**

`silk_reports.py` derives two more outputs from that same view — `render_docx()` (executive summary → competitive position → markets with a source line per number → "حدود هذا التقرير" limits section, needs `python-docx`) and `render_brief()` (decision + 3 sourced numbers + the two competitive-position lines, plain text). Served via `GET /analyses/{id}/report.docx` and `/brief`.

## Reverse discovery (the other direction)

`silk_discovery.py` flips the question: given a market, which HS codes look like real opportunities for a Saudi exporter? It reuses only the existing sources — `silk_data_layer.comtrade_trade()` for two signals (3-year import growth, and a "Saudi gap" where the market imports heavily, Saudi's share is low, but Saudi exports that code to the world) plus optional `silk_trends_agent` seasonality as a low-weight tiebreaker. No new API integrations — an AST-based test (`test_wave5a_discovery.py`) asserts the module imports nothing beyond that set. Exposed via `POST /discover`; a result's `hs_code` feeds straight into `analyze(hs_code=...)`, bypassing the resolver.

## Compliance checklists

`silk_requirements_agent.py` (the `with_requirements` enrichment flag) reads `data/requirements_l1.csv` — a static, offline reference of entry requirements per market/category plus Saudi-exit requirements, each row citing its regulation number and an official source URL. Rows are tagged with a codification tier (`مقنّن بالكامل` / `شبه موحّد` / `موثّق جزئياً`) reflecting how legible that market's rules are (EU numbered regulations vs. GCC unified standards vs. everything else). For animal-origin HS chapters into the EU, an eligibility check (EU 2017/625 listed-establishment status) is forced to the front of the list — no downstream item is shown as reachable until that gate is noted. This is a lookup table, not a live legal service; treat additions to the CSV as carefully as code (cite the regulation, don't invent one).

## BaseAgent and the paid/free boundary

All agents inherit `BaseAgent` (`silk_agents.py`) — 18 `BaseAgent` subclasses as of PR #83 (`grep 'class.*(BaseAgent)' silk_*.py`), which enforces the protocol structurally:

- `PAID = True` agents (LocalPrice, Volza, Explee — exactly these three) cannot execute outside the deepen context (`silk_context.deepen_context()`, a contextvar set only by `POST /deepen`). Outside it they return a tagged skipped report **without attempting any call**, even with keys set.
- An unexpected exception in `_execute()` automatically becomes a failed report with a noted DataPoint — silent failure is impossible.
- New agents: subclass `BaseAgent`, set `PAID`/`SOURCE`, implement `_execute(task) -> AgentReport`, and ship a hermetic test the same day.

`POST /analyze` (free path) structurally cannot trigger paid layers — its pydantic model has no paid fields, so they're dropped from any request body. `POST /deepen` is the only paid path.

Agent settings panel («إعدادات الوكلاء»): `silk_agents.AGENT_CATALOG` is the ONE catalog (key/name/role/paid) served via `GET /settings/agents`; each agent class carries a `PREF_KEY` pointing at a catalog row. `BaseAgent.run(task, instruction="")` enforces the panel structurally: a disabled row (`silk_context.agent_enabled`) returns a tagged skipped report with zero calls (same pattern as the PAID guard), and the effective command (explicit `instruction` arg wins over the saved one) is passed as `task["instruction"]` and declared in the report summary. Commands steer presentation/focus ONLY — a data agent's numbers are never altered (CompetitionAgent top-N is row-count only) and Claude agents receive the command inside `_isolate` via `silk_ai_judge._user_steer(key, extra)`. Settings persist server-side as one JSON row (`silk_store.save/load_agent_settings` — outside the env-key allowlist, so the panel can never smuggle a source key; keys stay in Railway env). `/analyze` requests without `agent_prefs` inherit the saved settings; `/deepen` is not gated by the panel (an explicit paid request wins). Disabling the `synthesis` row stops synthesis stage 2 only — stage 1 (deterministic jury) can never be turned off.

## Security guards (all run BEFORE any agent)

Configured via env vars (`.env.example` documents all of them); unset = open dev mode, which is legitimate **only when no paid keys are present**:

- `SILK_API_KEY` → requests without a matching `X-API-Key` header get 401.
- `SILK_PAID_DAILY_CAP` → paid-layer activations counted in a separate SQLite file (`data/usage.db` / `SILK_USAGE_DB`, never `silk.db`); exceeding = 429.
- Any paid provider key present while `SILK_API_KEY` is unset → paid requests get 503 and `/health` carries a warning.
- `CORS_ORIGINS` → default is same-origin only; wildcard requires explicit opt-in.
- Prompt injection: every external text reaching Claude goes through `silk_ai_judge._isolate()` (`[RAW_FINDINGS_START/END]` delimiters, with the delimiters themselves sanitized out of the content).
- `GET /diagnostics` is auth+rate-limit guarded (it fires live probes with the server's keys), and probe error details are secret-redacted (`silk_diagnostics._redact`) before leaving the server.
- Free-path Claude extras (consumer-culture extraction, entity qualification, and — since P5 — the stage-2 synthesis judge + `ai_report` via `policy["with_ai"]`) are context-gated: blocked when `ANTHROPIC_API_KEY` is set without `SILK_API_KEY`, otherwise one activation is reserved from the same `SILK_PAID_DAILY_CAP` counter per `/analyze`; exhaustion degrades with a declared `ai_extras_note`, never a 429 on the free path (`silk_context.block_ai_extras()` → `silk_ai_judge.available()`).

## Testing conventions

Tests are hermetic and live in `tests/test_smoke.py` + `tests/test_wave*.py`. Reused patterns: `_block_network()` (monkeypatch `socket.socket`) for library-level tests; `patch("requests.get", side_effect=OSError(...))` for FastAPI `TestClient` tests (blocking sockets globally breaks the TestClient transport); `_env(**vals)` context manager for env vars with guaranteed restore. The vision's acceptance criteria (§1.7, §11.5, §12.7) exist as named tests — keep that mapping when touching those areas.

## Storage

SQLite only (`silk_storage.py`, default `data/silk.db`) — Postgres migration is an explicitly deferred owner decision; don't introduce it. Schema changes go through additive `ALTER TABLE` migration inside `init_db()` (existing rows untouched). `analyses` carries `outcome`/`outcome_date` (the cumulative track record) settable via `PATCH /analyses/{id}/outcome`. Never delete or modify existing data in `data/silk.db`.

Persistence on Railway (persist-1…5): one env var `SILK_DATA_DIR=/data` routes all four stores (analyses DB, fact store `silk_store.db`, `usage.db`, request cache `cache/`) to the mounted volume; explicit per-store vars (`SILK_DB`/`SILK_STORE_DB`/`SILK_USAGE_DB`/`SILK_CACHE_DIR`) win individually, and `/health` exposes the resolved paths. The core agents and `market_imports_cached` are store-first: a store-served value keeps its ORIGINAL `retrieved_at` and carries «من المخزن» + the fetch date in its note — never present it as freshly live. Freshness windows (`silk_store.fresh_days`/`freshness`, `SILK_FRESH_*_DAYS`) drive stale-while-revalidate: stale hits are served immediately flagged `status="stale"` with a background re-fetch; `fetch_failed` ≠ `no_record` stays distinct. Periodic refresh is an in-process thread (`SILK_REFRESH_HOURS`, `silk_collectors.start_scheduler`) because a Railway volume mounts to exactly one service — don't move it to a separate cron service. Per-analysis store/cache/live counters (`silk_context.begin_data_counter`) surface as `result["data_economics"]`; counting must stay a no-op side channel.

## Governance docs (read before large changes)

- `docs/VISION.md` — the target architecture (its header says so explicitly: actual state ≠ this doc).
- `docs/AUDIT_STATUS.md` — the audit method: every claim anchored to file:line; "not found" stated explicitly.
- `docs/EXECUTION_PLAN.md` — the wave plan (waves 0–5 are implemented and merged) and the owner's settled decisions: SQLite stays, wave-3 agents are the selective four, trade finance is deferred.

House rules that carried through every wave: one independent PR per work wave branched from fresh `main` (squash-merged, `title (#N)` style); the existing suite stays green and each wave adds its tests; PR descriptions anchor claims to file:line; every render-layer change regenerates the committed samples in `samples/` (rule §10.6 — reviewers open files from the repo, no attachment channels).

## Misc

- The repo is bilingual: Arabic-first docstrings/comments/docs with English mirrors. Match that style.
- `web/index.html` is a single self-contained vanilla-JS file; it consumes `result.view` from the API — extend the view, then render it.
- The ponytail plugin is configured in `.claude/settings.json` (YAGNI, stdlib-first, minimal code) — the codebase follows it: no heavy frameworks, lazy imports so every module imports offline and keyless.

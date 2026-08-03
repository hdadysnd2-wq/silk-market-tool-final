---
name: silk-operations
description: Permanent operations reference for this repo — the money path, the sanitizer chain, where the escalation loop lives, the observability endpoints, and the incident-response protocol that produced every fix in this file. Load before touching silk_usage.py/silk_context.py, before diagnosing a live production failure, or when the owner pastes evidence from a real run and asks "why did this happen."
---

# Silk operations — the permanent cycle so no future session re-learns it

This skill exists because the exact same cycle repeated across a dozen PRs this
project: owner pastes live evidence → root cause traced to one file:line → fix
shipped with a lock-test using the verbatim production string → next incident,
same shape, different symptom. That cycle is now written down once, here,
instead of being re-discovered every session. **Update this skill at the end of
every work package** (see the closing rule) — a skill that goes stale is worse
than no skill, because it looks authoritative while being wrong.

## 0. THE FREEZE — post-merge, incident response only (owner authority)

**بعد الدمج، النظامُ مُجمَّد.** لا ميزة جديدة، ولا إعادة هيكلة، ولا «تحسين»
استباقي — **إلا بموافقة المالك الصريحة**. العمل المسموح بلا إذن جديد محصورٌ في
**الاستجابة للحوادث**: بلاغ حيّ بدليل → سبب جذري من الشيفرة → إصلاح عند الطبقة
الصحيحة + اختبار قفله في نفس الـPR (البروتوكول §4). أيّ شيء أوسع من ذلك —
ميزة، تبسيط، ترحيل، تعديل نطاق — يتطلّب أمراً صريحاً من المالك عبر تسلسل القيادة
(‏CLAUDE.md §LAW: المُشرِف Fable 5 يوجّه، المُنفِّذ ينفّذ، المالك يوافق).

**Post-merge the system is FROZEN.** No new feature, refactor, or speculative
"improvement" ships without the owner's explicit approval. The only work
allowed without a fresh owner order is **incident response**: live evidence →
root cause from code → fix at the right layer + its lock-test in the same PR.
Anything broader — a feature, a cleanup, a migration, a scope change — needs an
explicit owner order through the chain of command (CLAUDE.md §LAW). When in
doubt, it is frozen; ask, do not proceed.

هذه القاعدة تحرس ضدّ التوسّع الزاحف بعد أن يستقرّ النظام: كل تغيير غير حادثيّ
سطحٌ جديد لخطأ جديد. «إن لم يكن بلاغاً، فهو مُجمَّد.»

## 1. THE RULES — non-negotiable, checked on every PR

1. **No fabrication.** A missing value is `None` + `confidence=0.0` + a
   declared note — never a guess, never a silent zero (CLAUDE.md's founding
   principle; it governs every data path in this repo, not just the obvious
   ones).
2. **Fix from evidence, never guess.** Reproduce via trace/test/direct
   execution before writing the fix. When you cannot get evidence (network
   blocked, no live key), say so explicitly and ship instrumentation instead
   of a guess (`writer-timeout-open-case` is the canonical example: three PRs
   of instrumentation, zero speculative fixes, before the fourth failure
   self-diagnosed).
3. **Every fix ships with its lock-test in the same PR.** Not a follow-up, not
   a TODO — the same PR. A fix without a test is a fix that regresses silently
   next quarter.
4. **Flags default to current behavior.** A new env var, a new query
   parameter, a new instrumentation hook — all default to the pre-existing
   behavior when unset. #96's `mission_context` is the model: no flag exists
   at all, it is unconditionally wired in, because the safe default for pure
   measurement is "always on," not "on when someone remembers to enable it."
5. **Never weaken a guard to silence it.** If a fix would make a guard stop
   catching a real problem (dropping paragraphs instead of raising, loosening
   a regex until it stops matching anything), that is not a fix — find the
   fix that keeps the guard's teeth (§2's "sanitizer translation" trap is the
   proof: a paragraph-drop backstop was tried and reverted because it broke
   `test_guard_rejects_export_when_forbidden_term_leaks`).
6. **Sample noise gets reverted, never committed.** Running the test suite or
   a sample generator can rewrite `samples/*.docx`/`.json` with nondeterministic
   proxy-port numbers, timestamps, or docx zip-serialization noise. Diff before
   committing (`git diff --stat samples/`); if the only change is noise,
   `git checkout -- <file>` it back. A real render-layer change still must
   regenerate and commit samples (rule §10.6) — the discipline is "check before
   you commit," not "never touch samples."
7. **Docs/skills referenced across sessions MUST merge to `main` in the same
   package that creates them.** The lesson: PR #92 (`docs/FULL_AUDIT_2026-07-15.md`)
   was created, read from, and cited by file:line in three subsequent PRs —
   but never merged itself. A later session asked "confirm ITEM 5/7 landed"
   and the honest answer required grepping `git log --all` to discover the
   audit doc doesn't exist on `main` at all. A doc that only lives on an open
   branch is invisible to the next session and to anyone who didn't happen to
   read this exact PR. If you create a doc/skill and reference it from other
   work, merge it — don't leave it as a permanently-open PR.

## 2. THE TRAPS — each one bit a real PR

| Trap | What happened | Proving PR |
|---|---|---|
| **Mock-passes / real-fails** | `render_docx` had a research branch and was tested against a `markets:[]`+`deep_research{...}` fixture; `render_markdown` had the *same* fixture available in a sibling test file but was never actually called with it — so its missing research branch shipped untested. The fix: lock-tests must use the exact persisted blob shape (`markets:[]`, `deep_research{missions,analyst,verdict,report,trace_id,budget_status}`, reconstructed from the code that writes it), not a fixture that only proves a *different* function works. | #94 |
| **`markets:[]` misroutes exporters** | A `/research` result always has `markets:[]` (one market analyzed in depth, no ranking) — any render path that does `(view.get("markets") or [{}])[0]` silently gets `{}` and produces an empty `/analyze`-shaped page. Check which template a code path assumes *before* trusting its output for a research result. | #94 |
| **Two different sanitizers, don't assume one covers the other** | `silk_render._strip_internal_plumbing` (general — report.md, `/ask`, `/brief`, ops-log) translates *English* judgment words to Arabic (`confidence`→«درجة الثقة»). `silk_reports._CLIENT_SANITIZE` (client-docx only) additionally converts *that Arabic form* to commercial phrasing, because the client guard (`_client_assert_clean`) forbids «درجة الثقة» in client output. A string already containing the Arabic form (e.g. a guard's own rejection message quoting the matched text) passes through `_strip_internal_plumbing` completely unchanged — it isn't the client sanitizer, so it doesn't know client-forbidden Arabic terms. Know which of the two a given surface needs; don't sanitize with the general one and assume client-safety. | #94 (root cause); rediscovered while building the ops-observability endpoints (this package) — see the export-failure design in §3 |
| **Redaction mangling token-like strings** | `silk_diagnostics._redact` (`silk_diagnostics.py:26-43`) does a boundary-free `text.replace(env_key_value, "<ENV>")` for every configured provider key — no minimum length guard. A hermetic test using a short placeholder key (`"tok"`) meant every occurrence of the substring "tok" anywhere in diagnostic text got mangled, including an internal stage name (`draft_maxtok_retry1` → `draft_<ANTHROPIC_API_KEY>_retry1`). Fixed by renaming the stage to avoid the substring (`draft_escalate1`) — a **workaround, not a structural fix**; `_redact` itself still has no word-boundary/min-length guard (tracked MEDIUM in the audit, unfixed). Don't name anything with a short, common substring near diagnostic/redacted code paths until that guard exists. | #91 (workaround); structural fix still open |
| **Parallel missions and the cache window** | The 12 missions run via `ThreadPoolExecutor` + `contextvars.copy_context()` per task — genuinely parallel, not sequential. Anthropic's prompt caching keys off a time-bounded cache window; firing all 12 missions' first calls simultaneously can mean several land outside each other's cache window and none gets a cache hit, when a small stagger or sequential-batching would let later calls hit the earlier ones' warm cache. **Known, not yet fixed** — Part C step 3 (batch into 2-3 sequential groups) is the proposed remedy, pending real per-mission cache-hit data (now measurable via #96's `mission_usage`) to confirm it's worth the added latency. | Not yet — flagged in the live-audit cost analysis (§5 of `docs/FULL_AUDIT_2026-07-15.md`), Part C work item |
| **Cap counted operations, not dollars** | `SILK_PAID_DAILY_CAP` reserves exactly **one unit per `/research` invocation**, regardless of the run behind it costing $0.20 or $7.40 — a request-rate limiter, not a spend limiter. An operator setting `SILK_PAID_DAILY_CAP=10` believing it bounds cost was actually authorizing up to 10× the *worst-case* run cost per day. Fixed by adding a genuinely dollar-denominated ceiling (`SILK_PAID_DAILY_USD_CAP`) with its own atomic reserve (`try_reserve_usd`, `silk_usage.py:181`) alongside — not replacing — the count-based cap. | pre-#93 (finding); #93 (fix) |
| **Styled-but-never-wired UI affordance** | The «التحليلات الأخيرة» sidebar rail (`#histList`) rendered real past analyses and had `.hist{cursor:pointer}` + a hover style — every visual signal of a clickable "reopen" feature — but `drawHist()`/`pushHist()` never stored an `analysis_id` per entry and no click listener was ever attached to `#histList`. Clicking did *structurally nothing*, which read exactly like the auth-hardening on `GET /analyses*` (C-1, correct and intentional) had silently broken a fetch — it hadn't; there was no fetch to break. **CSS that signals interactivity is not evidence the interactivity was ever built** — verify the actual event-listener wiring before attributing a "click does nothing" report to a recent, unrelated change. Fixed: each hist entry now carries `data-id`; a delegated click handler opens the analysis or shows a visible Arabic message (401 → the exact "يتطلب مفتاح الخدمة" string; legacy entry with no stored id → a distinct message) — never a silent no-op. | #98 |
| **The #98 bug *family* (silent no-op has three forms, not one)** | A full functional audit of `web/index.html` (multi-agent workflow, 6 lenses + adversarial verify) found the sidebar defect was one instance of a family: (1) *visual-clickable ≠ wired* (a `cursor:pointer` element with no listener, or `#sendBtn` never disabled while `S.busy` so a click during a run no-ops); (2) *data-in-view ≠ rendered* (`year_fell_back`/`data_year` present in the view JSON but never drawn on the board, so an older published year reads as current — a founding-principle honesty gap the docx/md/terminal renderers all disclose); (3) *read-path-A-works ≠ read-path-B-works* (see the row below). The audit rule: **an action must succeed OR show a visible status — never a silent return, a stuck busy state, or a swallowed `catch`.** Six confirmed empty-`catch`/silent-no-op sites remain MED/LOW (owner-gated) in `docs/UI_AUDIT_2026-07-15.md`. | #98 (found); this package (5 HIGH fixed) |
| **view attached AFTER persist on one path, BEFORE on another** | `GET /analyses/{id}` returned the stored blob verbatim. Classic `/analyze` persists **inside the engine** (`silk_engine.py:619`) *before* the API attaches `result["view"]` (`api.py:579`), so its stored blob has **no** `view`; `/research` attaches `view` (`api.py:934`) *before* `save_analysis` (`api.py:955`), so its blob **has** one. Result: the #98 sidebar-reopen fix worked for research rows but opened a **blank board** for every classic row — a defect *inside the very fix we shipped*, invisible to a `web/index.html`-only reading (it's a client×server interaction; the completeness-critic caught it, not the six lenses). Fix: `GET /analyses/{id}` rebuilds `view` when missing (`found["view"]=_view(found)`), matching what `brief`/`report.md`/`report.docx` already do — never trust a persisted blob to carry a derived field. | this package |
| **`_strip_internal_plumbing` leaked three raw forms** | The general sanitizer (`silk_render._strip_internal_plumbing`) shipped three live-verified leak forms at once: (1) a raw `DataPoint(value=…, source=…, confidence=…, …)` repr was **half-translated** — `_EN_FIELD_RE` rewrote `confidence`→«درجة الثقة» while the `DataPoint(…)` wrapper and `value=`/`source=` stayed, producing a Frankenstein; (2) embedded JSON with `score`/`summary` keys slipped through because those keys were **absent from `_INTERNAL_JSON_MARKERS`** (only the whole-JSON path handled `summary`, not the embedded-behind-prefix path); (3) the raw verdict token match (`_RAW_VERDICT_RE`) was **case-sensitive**, so `go`/`Watch`/`no-go` survived untranslated. Fix: neutralize a `DataPoint(…)` repr **wholly** (extract `value` or declare a gap) *before* any field translation — never half-translate a repr; add `"score"`/`"summary"` to the markers; add `re.I` to the verdict regex (`verdict_ar` already upper-cases internally). Three verbatim-string guards in `test_regression_registry.py`. | closure package |
| **Orphaned runs leak their USD reservation** | A process death mid-`/research` (Railway redeploy, SIGKILL) never runs `mark_research_failed` or `reconcile_usd`, so the row is stuck `status='running'` **forever** and its pre-reserved USD (`try_reserve_usd`, default $3) is never reconciled — it accumulates in the daily bucket and jams `SILK_PAID_DAILY_USD_CAP` on runs that never finished (`reconcile_usd`'s own contract: "a run that crashes before reconcile keeps its full reservation"). Fix: `silk_storage.reap_orphan_research_runs` — a sweep (at **startup** in `api.create_app`, and **periodically** in `silk_collectors._loop`) that marks `running` rows older than `SILK_ORPHAN_STALE_MINUTES` (default 30, > the ~10-min longest legit run) as `failed`, and reconciles each leaked reservation to **actual-so-far** (last progress snapshot's `cost_usd_estimate`; missing → 0.0, no fabrication) — only for reservations in today's bucket (`reconcile_usd` operates on today; a prior-day reservation already cleared on the daily rollover). Mission checkpoints survive for resume. | closure package |

## 3. THE MAP — where the load-bearing pieces actually live

| Concern | Lives in | Not in (common wrong guess) |
|---|---|---|
| **Money guards** (atomic reserve, fail-closed) | `silk_usage.try_reserve_paid_calls` (`silk_usage.py:255`, count cap) and `try_reserve_usd` (`silk_usage.py:181`, dollar cap) — both `BEGIN IMMEDIATE` (write lock before read, no TOCTOU window), both fail-closed on any DB error (a corrupt counter denies spend, never allows it silently) | `would_exceed_cap`/`would_exceed_usd_cap` — these are **read-only pre-checks**, never the enforcing path |
| **General sanitizer chain** | `silk_render._strip_internal_plumbing` (`silk_render.py:692`) — fixed order: strip raw JSON leak → strip mission-key prefix → `LLMAgent:`/`LLMMissionAgent:` tag → `dp7`-style citation tags → EN confidence-decimal phrase → EN field name (verdict/confidence) → raw verdict token → `silk_narrative.humanize_technical_note` (catches `stop_reason`/`empty_response`/exception classes/"راجع سجلّات الخادم" — the last-resort net) | Order matters — `humanize_technical_note` runs *last* specifically to catch whatever the earlier specific patterns missed |
| **Client-docx sanitizer** (a *different*, stricter chain) | `silk_reports._client_sanitize` (`silk_reports.py:1332`) + hard-reject `_client_assert_clean` (`silk_reports.py:1352`) — forbids mission/status/run/call/tool-name/algorithm-language vocabulary entirely, converts what it can, raises `RuntimeError` on anything left | Do not assume `_strip_internal_plumbing` alone makes text client-docx-safe — see the trap table |
| **max_tokens escalation loop** | **The writer layer**, `silk_ai_judge.deep_report` (`silk_ai_judge.py:739`) — each retry is an independent traced call (own `report_call` event, own `llm_calls` increment, own token metering). **Not** `silk_llm_provider.complete` (single-shot HTTP seam only, exposes `last_stop_reason()` for the writer to read) | #90 had it inside the provider (every caller inherited transient escalation); #91 moved it and reverted non-writer sites to single-shot — deliberate, documented, not a regression (only the writer produces `report=None` and only it needs the retry) |
| **Live progress snapshots** | `silk_context.snapshot_research_progress(analysis_id, stage)` — reads the *existing* `data_counter()`/`estimate_cost_usd()`, writes to `analyses.progress_json` (additive column, `silk_storage.update_research_progress`/`get_research_progress`). Called from `silk_missions._checkpoint` (after each mission), `api.py`'s pipeline (stage transitions), and `write_reviewed_report(on_stage=...)` (writer↔reviewer sub-stages) | No new counter — this is a *snapshot* of counters that already existed for the final report |
| **Per-mission cost attribution** | `silk_context.mission_context(key)` (contextvar, same pattern as `agent_prefs_context`) + `record_llm_usage`'s additive tag into `data_counter()["mission_usage"][key]`. Wired unconditionally in `silk_llm_runtime.run_llm_agent` (`silk_llm_runtime.py:1017`) — every mission is tagged automatically, no per-mission code changes needed | Before this, `llm_usage` aggregated by **model only** — with all 12 missions sharing Opus, per-mission cost was structurally unanswerable from any existing artifact, trace included |
| **Operator self-service** | `GET /analyses/{id}?economics=1` (focused cost/usage summary, not the full blob) and `GET /ops/last-errors` (`silk_ops_log.py` — a capped SQLite ring, `record_error`/`last_errors`) | Both reuse `_require_key`/`_rate_limit` — there is no separate "operator" auth tier in this codebase; `/diagnostics` uses the exact same pattern |
| **UI functional state / the button inventory** | `docs/UI_AUDIT_2026-07-15.md` — authoritative inventory of all 37 interactive elements in `web/index.html` (element → handler → endpoint → visible-success/visible-failure), every confirmed #98-class finding by severity, and the Arabic operator button-map (زر → فعل → مجاني/مدفوع → ماذا ترى عند الفشل). Regenerate the same way (multi-agent workflow, adversarial verify) when the dashboard changes materially. | Not a live registry — a point-in-time audit; re-run rather than hand-patch when `web/index.html` changes a lot |

## 4. INCIDENT PROTOCOL — the mechanical loop

1. **Evidence arrives** (owner pastes a real response body, a trace excerpt, a
   screenshot). Do not theorize before reading it literally.
2. **Confirm root cause from code**, not from memory of a similar-sounding past
   incident. Read the actual file:line the evidence points at. If the evidence
   doesn't uniquely identify a cause, narrow by elimination (check every other
   candidate explanation and rule each out explicitly) — `docs/DEEP_RESEARCH_DECISIONS.md`'s
   evidence-labeling discipline requires stating which class of evidence you
   have: "direct reproduction," "static code review (file:line)," or "no
   sufficient evidence — pending" (never silently upgrade the last one to
   sound more confident than it is).
3. **Fix at the right layer.** A sanitization leak gets fixed in the render
   layer that builds the view, not by patching every consumer. A missing
   per-mission cost breakdown gets fixed by tagging usage at its source
   (`record_llm_usage`), not by trying to reconstruct it from timing data
   after the fact.
4. **Lock-test with the verbatim production string.** Not a paraphrase, not
   an idealized version — the exact string from the evidence (`"LLMMissionAgent:
   pricing_scout يقدّر الطلب dp7"`, `"stop_reason='max_tokens'"`, the literal
   guard-rejection message). A test built from a cleaned-up version of the bug
   can pass while the real bug still reproduces.
5. **Prove via the cheap path, never a full re-run.** `POST /analyses/{id}/report`
   (report regen, ~cents) proves any writer/render/sanitization fix against
   real stored data. A single-mission dry run (`deep_research(..., dry_run=True,
   only_agent=...)`, cost of one mission's budget) proves any mission-prompt
   fix. **Never loop a full `/research` (~$2-7) to test a fix** — see
   `credit-economics` for the full cheap-first ladder.

## 5. OPERATOR PLAYBOOK — دليل المشغّل (بالعربية كما طُلِب)

### تكلفة كل نوع عملية

| العملية | التكلفة التقريبية | ملاحظة |
|---|---|---|
| `/analyze` (مسار مجاني) | قريب من الصفر (مخزن حقائق أولاً) | يستهلك تفعيلة كلود واحدة فقط إن كان مفتاح Anthropic مضبوطاً |
| `/research` (بحث عميق كامل) | ~$1 دافئ الذاكرة المؤقتة ⟶ حتى ~$7.4 أسوأ حال (ذاكرة باردة + سقف نداءات مُستنفَد) | ~70% من التكلفة رموز إخراج Opus في الاثنتي عشرة بعثة |
| إعادة توليد التقرير (`POST /analyses/{id}/report`) | ~$1.5 أسوأ حال (نداء كاتب واحد + مراجع) | الطريق الرخيص لإصلاح فشل الكاتب دون إعادة البحث كله |
| `/deepen` (طبقات مدفوعة: Volza/LocalPrice/Explee) | يتفاوت حسب مزوّد البيانات | يحجز من `SILK_PAID_DAILY_CAP` قبل أي نداء |
| استئناف تشغيلة (`resume=<id>`) | صفر إن كانت مكتملة أصلاً (إعادة تسليم صرفة)؛ يعيد حجز الذيل إن كانت غير مكتملة | استعمل `resume` دوماً بدل تشغيلة كاملة جديدة بعد عطل |

### الأعلام القائمة وماذا يفعل كلٌّ منها

| العلم | يحدّ | لا يحدّ |
|---|---|---|
| `SILK_PAID_DAILY_CAP` | **عدد** تفعيلات الطبقات المدفوعة يومياً | الدولارات الفعلية (تشغيلة ~$7 = تفعيلة واحدة) |
| `SILK_PAID_DAILY_USD_CAP` | **الدولارات** المُقدَّرة يومياً (حجز ذرّي قبل البدء + مصالحة بعد الاكتمال) | — |
| `SILK_RESEARCH_MAX_LLM_CALLS` | نداءات كلود داخل حلقة البعثات الاثنتي عشرة فقط | ذيل المحلل/التوليف/الكاتب/المراجع (يتدهور رشيقاً حين يُستنفَد، لا يُلغى) |
| `SILK_MAX_TOKENS_RETRIES`/`_CEILING` | محاولات تصعيد سقف إخراج الكاتب عند الاقتطاع | أي موقع نداء آخر (مفرد الطلقة عمداً) |
| `SILK_OPS_LOG_CAP` | عدد صفوف سجل الأخطاء التشغيلية المحتفَظ بها (افتراضي 200) | — |

### كيف تقرأ `?economics=1` و`/ops/last-errors`

```bash
# ملخّص اقتصاد تشغيلة واحدة — لا البلوب الكامل
curl -sS "$BASE/analyses/$ID?economics=1" -H "X-API-Key: $KEY" | python3 -m json.tool
```
يعيد: `llm_calls`/`tool_calls`/عدّادات المخزن والذاكرة المؤقتة، `llm_usage` (لكل
نموذج)، `mission_usage`/`cost_usd_by_mission` (لكل بعثة — فارغان صراحةً
`mission_usage_available: false` لتشغيلة أقدم من هذه الميزة، لا خطأ)،
`cost_usd_estimate` النهائي، و`cost_unpriced_models` (نماذج غير مُسعَّرة —
التكلفة عندها جزئية صادقة لا مخفية).

```bash
# آخر ٢٠ خطأ تشغيلي (تصدير/كاتب/حجز) — بلا حاجة لسجلات Railway
curl -sS "$BASE/ops/last-errors?n=20" -H "X-API-Key: $KEY" | python3 -m json.tool
```
كل صفّ: `{"kind": "export_failure"|"writer_failure"|"reservation_refused",
"reason": "<سبب مُطهَّر>", "context": {...}, "at": "<توقيت>"}`. السبب لا يحمل
أبداً `stop_reason`/تتبّع استثناء خام — إن بدا سطر مريباً في هذا الردّ فهذا
انحدار في التطهير يستحق تقريراً فورياً.

### لقطة (snapshot) مقابل قياسي (standard) مقابل عميق (deep)

- **لقطة/معاينة فورية** (`POST /products/snapshot`): **مجانية دوماً منذ
  ITEM ٢** (تدقيق حي 2026-07-16) — نداء كلود (بعثة pricing_scout) أُزيل
  نهائياً؛ الآن مورّدو كومتريد فقط + المخزن أولاً، وأي أسعار منافِسة
  خُزِّنت قبل هذا القرار تبقى تُعرَض مجاناً. لا سعر منافِس على زوج جديد =
  فجوة معلنة مع توجيه صريح إلى `/research`، لا نداء كلود تلقائي يسدّها.
  زرّ «تحديث» يعيد الجلب (لا يزال مجانياً، بلا تأكيد).
- **قياسي** — المصطلح المستعمَل في تخطيط الموجة القادمة (Part C، البند ٤)
  لنسخة أرخص من `/research` تشغّل ست بعثات أساسية فقط (تجارة/منافسون/تسعير/
  جمارك/قنوات/طلب) بدل الاثنتي عشرة — **لم يُشحَن بعد**، مخطَّط فقط.
  عند شحنه سيكون هذا القسم أول ما يُحدَّث (راجع القاعدة الختامية أدناه).
- **عميق** (الوضع الحالي الوحيد المتاح فعلياً): الاثنتا عشرة بعثة كاملة —
  التكلفة والتفصيل في الجدول أعلاه.

---

## القاعدة الختامية — حدِّث هذه المهارة في نهاية كل حزمة عمل

كل PR يضيف بنداً جديداً لِـ**THE MAP** (مكوّناً جديداً)، أو **THE TRAPS**
(فخّاً وقع فيه فعلاً مع رقم الـPR المُثبِت)، أو يُحدِّث **OPERATOR PLAYBOOK**
(علماً جديداً، نقطة نهاية جديدة، وضعاً جديداً كالقياسي أعلاه) — **يُحدِّث هذه
المهارة في نفس الـPR**، لا في مهمة منفصلة لاحقة قد لا تأتي أبداً. مهارة
متقادمة أخطر من غيابها: تبدو موثوقة وهي خاطئة. إن لم تحدّثها، اذكر صراحةً في
وصف الـPR أنها لم تُحدَّث وسببَ ذلك.

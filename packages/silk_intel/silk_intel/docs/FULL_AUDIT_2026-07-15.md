# Silk Platform — Full Audit (2026-07-15)

> **Scope & method.** Read-only audit, zero live/paid calls, zero fabrication.
> Six parallel subagents covered the entire codebase incl. the frontend. Every
> finding carries `file:line`, severity, user-visible impact, and the exact test
> that would lock the fix. **Nothing was fixed in this pass — report only.**
> Audited: the code **as merged on `main` (post #90, `4d683f5`)** PLUS the **PR
> #91 branch diff** (`follow/writer-escalation-observability`). Behavioral
> differences between the two are flagged inline and summarized in §0.
>
> Severity: **BLOCKER** (data loss / money / security, must fix before shipping) ·
> **HIGH** · **MEDIUM** · **LOW**.

---

## Executive summary — top 10 findings (ranked)

| # | Sev | Finding | Anchor | User-visible impact |
|---|-----|---------|--------|---------------------|
| 1 | **HIGH** | **Regen silently destroys a good report.** `POST /analyses/{id}/report` unconditionally overwrites the stored blob with the new `report_out`; if the writer transiently fails it stores `report=None` and returns **200** — clobbering a previously-good report. | `api.py:1357-1365` | The exact deliverable regen exists to rescue is lost to a transient timeout; no error shown. |
| 2 | **HIGH** | **The daily cap is a request-rate limiter, not a spend limiter.** `SILK_PAID_DAILY_CAP` reserves **one unit per `/research` invocation**, regardless of the ~40–48 real Claude calls / ~$7 worst-case dollars behind it. | `api.py:1014` → `api.py:498` → `silk_usage.py:118` | `SILK_PAID_DAILY_CAP=N` authorizes up to **N × ~$7/day**, not N dollars. Operators cannot bound daily Claude cost. |
| 3 | **HIGH** | **The post-mission tail runs fully uncapped.** The run-wide `SILK_RESEARCH_MAX_LLM_CALLS=40` cap is consulted **only inside the mission loop** (`silk_llm_runtime.py:890-895`) and even there only turns tools off, never aborts. The writer(≤4 opus)+reviewer(≤2)+analyst+synthesis tail (~$1.9) runs even when the cap is already exhausted. | cap `silk_llm_runtime.py:890-895`; tail `api.py:815-827` | A run can blow past 40 calls with no governor; cost overruns are invisible until the bill. |
| 4 | **HIGH** | **Analyst intersection values leak raw plumbing to the client `/brief` and `/ask`.** `_deep_research_view` sanitizes only the analyst *summary*; `by_category[*].value/note` reach `render_brief` and the `/ask` context with **no sanitizer**. Proven: `view["brief"]` contained `LLMMissionAgent: pricing_scout … dp7`. | `silk_render.py:870-875`; `render_brief:592` | A paying client sees internal agent tags / `dp7` citation tokens in the one-page brief and chat. |
| 5 | **HIGH** | **`/ask` returns the raw `failure_reason()` as its `note`** (no sanitizer), and `_strip_internal_plumbing` leaves `failure_reason` tokens intact everywhere else. `empty_response`, `stop_reason='max_tokens'`, and the operator instruction `راجع سجلّات الخادم` survive to `/ask`, `/report.md`, and the operator docx limits. | `api.py:1397`; sanitizer `silk_render.py:891-899` | Client-facing surfaces show internal error plumbing and a "check server logs" instruction. |
| 6 | **HIGH/MED** | **Resume re-runs and re-pays the unmetered tail.** A resume of a non-completed run reserves **another** cap unit and re-executes the entire analyst+synthesis+writer+reviewer tail (~$1.8) even though all 12 missions are checkpointed. A redeploy auto-resuming several stuck runs multiplies it. | `api.py:956-977` (early-return `:969-974`); tail `:815-827` | Repeated resumes silently burn credits; each resume charges the operator ~$1.8 with no cap protection on the real spend. |
| 7 | **MED** | **Analyst is single-shot at 6000 tokens** — the largest prompt in the system (all 12 missions' findings + product card). Truncation → `_parse_output` yields zero findings → **all five intersections render "دليل غير كافٍ"** and `analyst_summary` is empty, starving the writer and judge. Present on **both** #90 and #91. | analyst `silk_market_analyst.py:186`; budget `silk_llm_runtime.py:49` | The report's analytical spine silently collapses on a long run; the user sees "insufficient evidence" despite real data. |
| 8 | **MED** | **Orphaned `/research` runs are stuck `"running"` forever.** A hard Railway redeploy SIGKILLs the daemon thread outside the try/except, so neither `completed` nor `failed` is written. No reaper, heartbeat, or startup sweep; `updated_at` frozen at creation. Recovery is manual `resume` only. | `api.py:894-912`; `silk_storage.py:169` | The dashboard polls a `"running"` run indefinitely (see #9-frontend); the operator has no signal it died. |
| 9 | **MED** | **`GET /diagnostics` fires live Claude + Serper + Maps probes with the server's keys and reserves nothing** against the cap. The only Claude/paid route with no reservation. | `api.py:1153` → `silk_diagnostics.py:175` | An authenticated caller can spend paid credits uncounted; repeated hits = uncapped spend. |
| 10 | **MED** | **Worst-case `/research` ≈ $7.40 (7.4× the ~$1 target); regen ≈ $1.53.** Dominated by opus **output** tokens (~$5.2, ~70%). The ~$1 figure holds only with warm cache + sub-cap output. Cold-cache + max-output + cap-saturated ≈ $7. | rates `silk_pricing.py:12-13`; arithmetic in §5 | Cost expectations are off by up to 7×; a single regen can exceed the whole-run budget. |

**One reassuring headline:** the **no-fabrication founding invariant is fully intact** across the entire data layer and all ~21 source agents — every failure path returns a tagged `None`/`0.0-confidence`, never a fabricated value or silent zero, with `fetch_failed` vs `no_record` preserved end to end (§6). The audit found **no BLOCKER and no fabrication defect.** The exposures are cost-governance and client-facing plumbing leaks, not data integrity.

---

## §0 — Behavioral difference: main (#90) vs PR #91

`api.py`, `silk_render.py`, `silk_reports.py`, the data layer, and the frontend are **byte-identical** between the two branches (`git diff origin/main -- api.py` is empty). The #91 diff touches only `silk_ai_judge.py`, `silk_llm_provider.py`, tests, and docs. The one behavioral change:

| Aspect | main (#90) | #91 |
|---|---|---|
| `max_tokens` escalation location | **Inside** `AnthropicProvider.complete()` — loops N POSTs internally (`silk_llm_provider.py:125-155` on main) | **In the writer** `deep_report` (`silk_ai_judge.py:980-999`); provider reverts to single-shot exposing `last_stop_reason()` |
| Who gets escalation | **Every** `complete()` caller (writer, synthesis judge, reviewer, `ai_report`, `/ask`, 4 extractors) inherited it | **Only the writer** |
| `llm_calls` count per escalated write | 1 (under-counts by attempts−1) | N (honest per attempt) |
| `$` / token metering | Accurate (per-POST) | Accurate (per-POST) |

**Two consequences to note.** (a) #91's per-attempt `llm_calls` counting is the stated goal and is correct — but it means writer escalations now increment the shared `data_economics` counter, which is **latent risk** if the cap were ever extended to the tail (a single escalating write could self-truncate). (b) #91 **silently reverts synthesis/reviewer/`ai_report`/extractors to single-shot** — an undocumented side effect (LLM-F2); those sites lose the transient escalation #90 gave them. Neither is a regression in the reported failure (the writer, the only site that matters for `report=None`, keeps escalation on both). The #91 escalation loop itself was verified correct: bounded (≤2 real attempts, 4-count cap), escalates only on `max_tokens`, and **preserves the longest partial even when the final attempt network-fails** (no discard bug).

---

## §1 — API surface (24 routes, `api.py`)

**Findings** (full detail in the source agent report):

- **HIGH · Regen non-atomic data loss** — `api.py:1357-1365`. Case (d) of the regen matrix: writer returns `None` → `found["deep_research"]["report"] = report_out` (null) → `save_analysis` UPDATEs the blob + `status='completed'`, returning 200. Prior good report clobbered. Lock: `test_regen_writer_failure_preserves_prior_report`.
- **MED · `/diagnostics` uncounted paid spend** — `api.py:1153` → `silk_diagnostics.py:175`. Live Claude/Serper/Maps probes, no `try_reserve_paid_calls`. Auth+rate-limit guarded but not cap-guarded. Lock: `test_diagnostics_probe_reserves_or_is_exempt_from_paid_cap`.
- **MED · report/brief/docx bypass the `_view()` safety net** — `api.py:1250,1275,1289,1312`. Call `build_view` directly; `report.docx` catches only `RuntimeError` (`:1289`) → any `KeyError/ValueError/TypeError` on a malformed blob = unhandled 500. Lock: `test_report_endpoints_degrade_when_build_view_raises`.
- **MED · Orphaned run stuck `"running"` forever** — `api.py:894-912`, `silk_storage.py:169`. SIGKILL bypasses the try/except; no reaper/heartbeat/startup-sweep (grep-confirmed). Lock: `test_orphaned_running_research_run_is_detectable_or_reaped`.
- **LOW · async-without-persist consumes a cap unit before 400** — `api.py:1014` runs before the `async_requires_persist` 400 at `:1041`. Lock: `test_async_research_without_persist_does_not_consume_cap`.
- **LOW · `/health` has no rate-limit** — `api.py:262`. Only reference route without `_rate_limit`. Lock: `test_health_is_rate_limited`.

**Paid-cap coverage table — every Claude/paid route reserves EXCEPT `/diagnostics`:** `/analyze` (`_free_ai_extras_allowed` `api.py:545`→`498`), `/deepen` (`_guard_paid` `:692`→`443`), `/research` (`:1014`), regen (`:1342`), `/ask` (`:1388`), snapshot (`:1469`, confirm-only) — all ✅. **`/diagnostics` (`:1153`) — ❌ no reservation.** All reserve **1 activation** regardless of internal call volume (this is the design; see §5).

**Regen behavior matrix:** (a) missing id → 404; (b) not-research → 400; (c) no checkpoints → 409; (d) writer fails → **200 with null report + prior report clobbered** ← the defect; (e) cap exhausted → 200 `{report:None, note}` *without* saving (safe). Only (d) persists a null; a test must exercise (d) specifically (AI available, writer returns None).

---

## §2 — LLM runtime + provider + call sites

**Per-call-site failure behavior** (C = `complete()` single-text; CT = `complete_tools()` tool-loop):

| Site | Seam | max_tokens | Escalation (#91) | On failure the USER sees |
|---|---|---|---|---|
| Writer `deep_report` | C | 8000→16000 | **YES** (only site) | recovered text, or declared gap (never `report=None` from max_tokens) |
| Reviewer `review_report` | C | 900 | NO | draft ships **unreviewed** silently on any reviewer failure |
| Analyst `analyze_market` | CT | **6000** | NO (never had it) | **all 5 intersections "دليل غير كافٍ"** on truncation (F1) |
| 12 missions | CT | 4000 | NO | that mission's findings dropped → section declares a gap |
| Synthesis stage-2 | C | 900 | NO (#91 reverted) | falls back to deterministic jury (safe) |
| `/ask` | C | 700 | NO | **truncated mid-sentence answer** on max_tokens-with-text, no flag |
| Snapshot | CT | 1500 | NO | `competing=[]`, weakened "worth full study" |
| Extractors ×4 | C | 500-1200 | NO (#91 reverted) | `None` → feature absent (declared) |
| `ai_report` | C | 1800 | NO | truncated narrative |

**Findings:**
- **MED · Analyst single-shot truncation** (F1) — `silk_market_analyst.py:186`, budget `silk_llm_runtime.py:49`. Highest-impact unprotected site; on both branches. Lock: `test_analyst_truncated_at_max_tokens_declares_gap_not_silent_empty`.
- **MED · #91 undocumented escalation revert** (F2) — `silk_llm_provider.py` single-shot vs main. Lock: `test_synthesis_judge_max_tokens_falls_back_to_jury_single_shot`.
- **LOW-MED · `_redact` over-breadth** (F3) — `silk_diagnostics._redact:40` does a boundary-free `str.replace(keyval, "<ENV>")` with no min-length guard. #91 only renamed the `maxtok` stage to dodge it — the naive replace is unchanged; a short/common key value mangles product names, source names, mission keys, prompts in trace / `/diagnostics`. Production risk LOW (real keys are long), but latent. Lock: `test_redact_does_not_mangle_legitimate_text_when_key_is_short`.
- **LOW · mission/snapshot truncation drops findings** (F4); **LOW · `/ask`+`ai_report` truncated text unflagged** (F5); **LOW · `llm_calls` under-counts an empty-text-max_tokens attempt** (F6, `silk_ai_judge.py:155-164`).

The #91 escalation loop is **correct** (bounded, escalates only on max_tokens, preserves longest partial across a final network failure) — no bug in the loop itself.

---

## §3 — Frontend (`web/index.html`, 790 lines)

**No BLOCKER; no XSS via the primary render path** (every deep-research field is `esc()`'d). Findings:

- **HIGH · `dlReport("md")` has no `r.ok` check** — `web/index.html:679`. A 401/404/500 body is rendered to the user as if it were the report markdown (the docx branch at `:676` checks `r.ok`; md does not). Lock: `test_md_download_guards_response_ok`.
- **HIGH · No in-flight disable / debounce on export buttons** — `:681,682,731`. Double-click = duplicate `report.docx`/`.md` requests + double download. Lock: `test_report_buttons_disable_during_fetch`.
- **MED · `degraded_reason` bypasses the server sanitizer** — read `:552`, produced raw `silk_render.py:933`/`api.py:870`; the readiness variant (`api.py:528` "راجع سياق التشغيل الحالي") is operator plumbing on the most prominent red banner. `esc()`'d so no XSS. Lock: `test_degraded_reason_stripped_of_plumbing`.
- **MED · Status polling never stops** — `:497`. Fixed 1.5 s, no backoff, no max-attempt cap, no `visibilitychange` pause; `stopResearchPoll` never called on `nav()`. An abandoned tab on a stuck `"running"` run polls forever (compounds §1 orphan). Lock: `test_poll_has_cap_and_stops_on_nav`.
- **MED · Unescaped drawer catalog strings** — `:752`. `a.n/a.d/a.k` from `GET /settings/agents` inserted via `innerHTML` without `esc()` (and `data-k="…"` unquoted-escaped), unlike every other server string. Defense-in-depth gap. Lock: `test_drawer_escapes_catalog_name_role_key`.
- **LOW:** silent `/markets` bootstrap failure (`:414`); `chatAdd` raw-HTML contract (`:686`); no bidi isolation on mixed AR/Latin (`:89,554,586`); failed-research leaves stale board + in-memory-only resume id (`:505-507`); empty-blob / popup-blocked exports silent (`:677,680`).

`analysis_id` gating verified sound for completed/degraded runs (`_finish_research_run` sets it at `api.py:890` before save) — export/ask buttons work on degraded-but-completed research. The "تعذّر إصدار توصية" state shows only the humanized label, no raw plumbing.

---

## §4 — Sanitization end-to-end (adversarial)

**Client docx is well-protected** (`_client_sanitize` + hard-reject `_client_assert_clean`, `silk_reports.py:1332,1352`). **Verified safe:** top-level `verdict.reasoning` does not exist (jury emits no such key); the degraded-docx note is a fixed literal (no `failure_reason` interpolation); the deliberately-retained Arabic `| نداءات أدوات: N` suffix has **no client path**.

**But three real leak classes reach client surfaces:**
- **HIGH · Analyst `by_category[*].value/note` → `/brief` (client) + `/ask` context, no sanitizer** — `silk_render.py:870-875` sanitizes only the summary; `render_brief:592`. **Proven** leak of `LLMMissionAgent: pricing_scout … dp7` in `view["brief"]`. Lock: `test_brief_analyst_values_are_sanitized`.
- **HIGH · `/ask` `note` = raw `failure_reason()`** — `api.py:1397`. Lock: `test_ask_note_is_sanitized`.
- **HIGH · `failure_reason` tokens survive `_strip_internal_plumbing`** — `empty_response`, `stop_reason='max_tokens'`, `راجع سجلّات الخادم` leak to `/report.md` limits + operator docx. Lock: `test_failure_reason_tokens_are_humanized_before_any_client_surface`.
- **MED · `/analyze` `decision.why` uses `ai.reasoning` RAW** — `silk_render.py:52` (asymmetry vs the sanitized deep-research path). Lock: `test_decision_why_is_sanitized`.

**Ten adversarial strings that leak through today's `_strip_internal_plumbing`** (each executed, not inferred) — each becomes a regression test:

| # | Input shape | Why it leaks | Proposed test |
|---|---|---|---|
| A | `LLMMissionAgent: key` (space after colon) | `_INTERNAL_AGENT_RE` allows no space; `_strip_mission_key_prefix` fires only at line-start | `test_strip_plumbing_catches_agent_tag_with_space_after_colon` |
| B | ` ```plain … ``` ` (non-json fence tag) | `_JSON_FENCE_RE` strips only ``` fences + the literal `json`; other tags leak as prose | `test_strip_removes_non_json_fence_language_tag` |
| C | lowercase `conditional-go` | `_RAW_VERDICT_RE` compiled without `re.I` | `test_strip_translates_lowercase_verdict_token` |
| D | `DataPoint(value=None, confidence=0.0)` repr | no pattern targets it; `_EN_FIELD_RE` garbles `confidence` inside it | `test_strip_neutralizes_datapoint_repr` |
| E | embedded JSON with keys not in `_INTERNAL_JSON_MARKERS` | not whole-JSON, no marker → embedded branch never triggers | `test_strip_catches_embedded_json_without_known_markers` |
| F | single-quoted `{'verdict': 'GO', …}` | markers are double-quoted; `json.loads` fails on single quotes | `test_strip_handles_single_quoted_verdict_blob` |
| G | `confidence=0.64` (`=` separator) | `_EN_CONF_VALUE_RE` separator class excludes `=`; raw decimal survives | `test_strip_phrases_confidence_value_with_equals_separator` |
| H | `stop_reason='max_tokens'` / `empty_response` | no `_TECH_PATTERNS` entry; `_EXC_CLASS_RE` needs an uppercase Error class | `test_failure_reason_tokens_humanized` |
| I | `راجع سجلّات الخادم` | no pattern removes it, despite the code comment claiming it is stripped | `test_strip_removes_check_server_logs_instruction` |
| J | `{"score":0.7,"summary":"جيد"}` embedded | `score`/`summary` not in markers → embedded branch never triggers | `test_strip_catches_score_keyed_embedded_json` |

---

## §5 — Cost, metering, caps (arithmetic)

**Rates** (`silk_pricing.py:12-13`): opus $5 in / $25 out per MTok; haiku $1 / $5. Cold-cache assumption (no 0.1× read discount).

**Worst-case one `/research`** (cap binds missions to ~40 opus calls):

| Stage | Calls | Input $ | Output $ | Subtotal |
|---|---|---|---|---|
| Missions (opus) | 40 | $1.600 | $4.000 | **$5.600** |
| Analyst (opus) | 1 | $0.060 | $0.150 | $0.210 |
| Synthesis (opus) | 1 | $0.040 | $0.0225 | $0.0625 |
| Writer (opus, ≤4) | 4 | $0.260 | $1.200 | **$1.460** |
| Reviewer (haiku, ≤2) | 2 | $0.056 | $0.009 | $0.065 |
| | | | | **≈ $7.40** |

Opus **output** ≈ $5.2 (~70%). **One regen** (writer $1.46 + reviewer $0.065) ≈ **$1.53**. The owner's ~$1/run holds only with warm cache + sub-cap output + missions below the 40-call cap.

**Cap coverage:** the run-wide cap (`silk_llm_runtime.py:890-895`) is **mission-loop only** and only turns tools off (never aborts). The tail (`api.py:815-827`) is uncapped — a cap-exhausted run still runs the full writer/reviewer/analyst/synthesis tail (~$1.9). **Findings F1 (HIGH, uncapped tail), F2 (HIGH, cap = request-rate not spend), F3 (MED, resume respend ~$1.8 + fresh unit), F4 (MED, `/research` drops `cost_estimate_complete`/`cost_unpriced_tokens` honesty flags — `api.py:837-839` vs `silk_engine.py:296-297`), F5 (LOW, regen never calls `begin_data_counter` so its cost is invisible).**

**All loops are bounded** (mission `max_rounds`, writer escalation retries+ceiling, reviewer `max_cycles=2`, run cap) — no unbounded path. **`estimate_cost_usd` itself cannot silently under-report** (post-#86 it flags `complete=False` + `unpriced_tokens`) — but `/research` drops those flags (F4). Proposed guard: surface the flags on `/research` (mirror `silk_engine.py:296-297`) **and** a `SILK_REQUIRE_PRICED_MODELS` health check that warns/409s when `_MODEL`/`_FAST_MODEL` fail `_pricing_for()`.

---

## §6 — Data layer + source agents + persistence

**The no-fabrication invariant is fully intact** — every one of ~21 fetchers/agents returns tagged `None`/`0.0-confidence` on failure, never a fabricated value or silent zero (full per-agent table with test refs in the source report). `fetch_failed` vs `no_record` is preserved (`silk_data_layer.py:317-326`). The 3 PAID agents are additionally structurally gated (zero calls outside `deepen_context()`).

**Verified correct:** Comtrade mirror fires only on empty-success (`silk_data_layer_v2.py:127-132`), confidence-capped 0.6, "(مرآة)"-tagged; world/partner reconciliation `max(world, partner-sum)` + >20% divergence flag (`:158-172`); FAOSTAT circuit breaker (`silk_faostat_agent.py:108-110`); GDELT/Trends degrade to declared gaps. SQLite money guard `try_reserve_paid_calls` uses atomic `BEGIN IMMEDIATE` + fail-closed (`silk_usage.py:139-155`); no money write lacks atomicity. The wave-13 hardcoded `"data/silk.db"` literal is gone; all stores route env-aware.

**Findings:** **F1 (HIGH, same as §5 F3, resume respends the unmetered tail); F2 (MED, cap under-accounts research); F3 (LOW, `record_paid_calls` dead code, `silk_usage.py:90-103`); F4 (LOW-uncertain, cached-path Comtrade error-envelope could misclassify fetch-failure as no_record — `silk_data_layer.py:312-317`, unconfirmed without reading `silk_cache`); F5 (LOW, thin no-fabrication test coverage for `openalex_search`, Maps `find_places`, `primary_qty`).**

**Checkpoint/resume:** exactly the 12 missions are checkpointed the instant each completes (`silk_missions.py:449`); the analyst/synthesis/writer/reviewer tail is **not** — it re-runs and re-spends on every resume (F1). Completed-run resume is a pure replay (zero calls); non-completed resume reserves a fresh cap unit + reruns the tail.

---

## Prioritized fix list (every HIGH carries its lock-test)

**BLOCKER:** none.

**HIGH — fix before relying on regen / before client-facing output / before scaling spend:**

| # | Fix | Anchor | Lock-test |
|---|-----|--------|-----------|
| H1 | Regen must not overwrite a good report with null — only persist a non-null report (or keep prior + attach `failure_reason`). | `api.py:1357-1365` | `test_regen_writer_failure_preserves_prior_report` |
| H2 | Sanitize analyst `by_category[*].value/note` before `/brief` and `/ask`. | `silk_render.py:870-875` | `test_brief_analyst_values_are_sanitized` |
| H3 | Sanitize the `/ask` `note` (run `failure_reason()` through the humanizer). | `api.py:1397` | `test_ask_note_is_sanitized` |
| H4 | Humanize `failure_reason` tokens (`empty_response`, `stop_reason=…`, `راجع سجلّات الخادم`) in `_strip_internal_plumbing`/`silk_narrative._TECH_PATTERNS`. | `silk_narrative.py:172`, `silk_render.py:891` | `test_failure_reason_tokens_are_humanized_before_any_client_surface` |
| H5 | Bring the writer/reviewer/analyst/synthesis tail under a run-level spend guard (or reserve per-stage / checkpoint the tail). | `silk_llm_runtime.py:890-895`, `api.py:815-827` | `test_tail_is_governed_when_run_cap_hit` |
| H6 | Make `SILK_PAID_DAILY_CAP` bound spend, not invocations — reserve proportional to expected calls, or add a separate dollar/day ceiling. | `api.py:1014`, `silk_usage.py:118` | `test_research_daily_spend_is_bounded_by_cap` |
| H7 | `dlReport("md")` must check `r.ok` before rendering the body. | `web/index.html:679` | `test_md_download_guards_response_ok` |

**MEDIUM (batch):** analyst single-shot truncation guard (`test_analyst_truncated_declares_gap`); `/diagnostics` reservation; report-endpoint `build_view` safety net; orphaned-run reaper/`stale-running` sweep; export debounce; `degraded_reason` sanitize; polling cap + `nav()` stop + `visibilitychange`; `/analyze` `decision.why` sanitize; the 10 adversarial sanitizer patterns (A–J); surface `/research` cost honesty flags (F4) + `SILK_REQUIRE_PRICED_MODELS`; document the #91 escalation revert (F2); `_redact` word-boundary/min-length guard.

**LOW (backlog):** regen cost visibility; `llm_calls` empty-max_tokens counter gap; mission/snapshot truncation declares a gap explicitly; `/ask`+`ai_report` truncation flag; `/health` rate-limit; delete `record_paid_calls` dead code; cached-Comtrade misclassification test; thin agent no-fabrication tests; frontend L-1…L-5; drawer catalog escaping; RTL bidi isolation.

---

## GO / NO-GO — the live Netherlands regeneration proof

**Recommendation: CONDITIONAL GO for a single, internal-capture regen — with two guardrails.**

Why GO is safe for this specific run:
- The Netherlands run's stored report is **currently `None`** (the writer failed). The regen data-loss bug (H1) **cannot destroy a report that is already null** — the first regen has nothing to clobber. If it succeeds, the report is stored; if it fails again, you get fresh trace evidence (no fabrication risk — §6).
- Cost is bounded: **≈ $1.53 worst case** for one regen (§5) — acceptable for one proof.
- The writer `max_tokens` fix (live on `main` as #90, refined in #91) recovers from exactly the failure that produced `report=None`, so the regen is expected to succeed.

**Must-fix BEFORE spending, depending on intent:**

| If you intend to… | Then fix first |
|---|---|
| Run the regen **once**, inspect the operator docx / view JSON internally | **Nothing blocks it — GO now.** (report is null; cost ~$1.5; no fabrication.) |
| Run regen **more than once** against the same id / make it a routine operation | **H1** (regen data loss) — a second failed regen would clobber the first good one. |
| Show the captured output to a **client** (via `/brief` or `/ask`, or commit it as the "first real client sample") | **H2, H3, H4** — analyst-value brief leak, raw `/ask` note, and un-humanized `failure_reason` tokens are client-facing. |
| Run **many** research/regen operations or rely on `SILK_PAID_DAILY_CAP` to bound cost | **H5, H6** — the tail is uncapped and the cap doesn't limit dollars. |

**Net:** a one-shot internal proof of the writer fix on the Netherlands run is **GO** today — it is cheap, cannot lose data (report is already null), and cannot fabricate. Anything beyond that one internal capture (repeat regen, client delivery, or budgeted scale) should wait on the HIGH fixes above, none of which is a blocker to the single proof itself.

---

### Appendix — provenance

Six parallel read-only subagents (API surface · LLM runtime/provider/call-sites · frontend · sanitization-adversarial · cost/metering/caps · data-layer/persistence), each anchoring to `file:line` and comparing `main`@`4d683f5` (post #90) against the `follow/writer-escalation-observability` (#91) diff. No live or paid calls were made; the sanitization leaks and the escalation-loop bound were verified by executing the functions directly on constructed inputs, not by inference. Every HIGH finding names the test that would lock its fix.

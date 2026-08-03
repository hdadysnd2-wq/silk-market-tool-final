---
name: research-debugging
description: Step-by-step playbook for debugging a bad or failed /research run in the Silk market-intelligence repo — trace-first, never guess, never re-run a full paid research to diagnose. Load whenever a /research run failed, hung on "running", produced a weak/empty report, or a mission returned "غير محسوم" or zero findings.
---

# Debugging a /research run — trace first, never guess

Every /research run writes a full JSONL trace. The answer to "why is this run bad?"
is almost always already on disk. Read evidence BEFORE touching prompts, budgets,
or timeouts. A full re-run costs ~$2 of the owner's credits — it is the last resort,
not a debugging tool (see the `credit-economics` skill).

## 1. First moves, in this exact order

1. **Per-mission state** (free, no key needed if run was persisted):
   ```
   GET /research/{analysis_id}/status
   ```
   Handler: `api.py:1077-1101`. Returns `status` (running/completed/failed),
   `missions` = `{mission_key: "pending"|<state>}` for all 12 keys from
   `silk_missions.MISSION_ORDER`, plus `missions_completed`/`missions_total`.
   - Stuck forever on `status: "running"` after a redeploy → see step 5 (resume).
2. **Read the trace file**: `data/traces/{trace_id}.jsonl`.
   - `trace_id` is in the result at `result["deep_research"]["trace_id"]`
     (`api.py:851`) and in the stored analysis (`GET /analyses/{id}`).
   - Directory override: env `SILK_TRACE_DIR` (`silk_trace.py:28-31`, default
     `data/traces`). Reader helper: `silk_trace.read_trace(trace_id)`
     (`silk_trace.py:109-124`) — returns `[]` for a missing file, no exception.
3. **Dashboard glance without opening JSONL**: the view carries
   `view["deep_research"]["missions"][key]["trace"]` =
   `{status, tool_calls, dropped, gaps}` — built by
   `silk_render._mission_trace_summary` (`silk_render.py:583-596`, attached at
   `silk_render.py:636`). `status` is `"succeeded"|"failed"|"skipped"`
   (skipped = summary contains "معطّل", i.e. disabled in «إعدادات الوكلاء»).
4. **Budget check**: `result["deep_research"]["budget_status"]`
   (`api.py:741-757`) names any hit cap explicitly, e.g.
   `{"exhausted": true, "caps_hit": ["SILK_RESEARCH_MAX_LLM_CALLS=40"], ...}`.
   A hit cap means missions were gracefully cut short — quality complaints may
   be a budget problem, not a prompt problem.
5. **Quality gate findings**: `view["deep_research"]["quality_gate"]`
   (`{"verdict": PASS|WARN|FAIL, "findings": [...], "methodology_notes": [...]}`,
   attached by `api.py:759-773`, computed in `silk_quality_gate.run_quality_gate`
   `silk_quality_gate.py:229-272`). A `analyst_layer_failed` finding
   (`silk_quality_gate.py:190-210`) means the analyst AND writer both returned
   None — that is a Claude-call failure, not a data problem.

## 2. Trace event anatomy

Written by `silk_llm_runtime._run_loop` and `silk_ai_judge._traced_call`.
Every string passes `silk_diagnostics._redact` before hitting disk
(`silk_trace.py:63-72` `_redacted`, applied in `_write_event` `silk_trace.py:75-84`)
— secrets never appear in traces.

| kind | Written at | Key fields |
|---|---|---|
| `llm_call` | `silk_llm_runtime.py:736-740` (success), `729-734` (failure) | `mission`, `round`, `tools_offered` (bool), `elapsed_ms`, `stop_reason`, `system_prompt`, `last_user_message`; on failure instead `result="no_response (<reason>)"` where reason comes from `failure_reason()` (imported as `_ai_failure_reason`, `silk_llm_runtime.py:36`) |
| `tool_call` | `silk_llm_runtime.py:766-772` | `mission`, `round`, `tool`, `input` (exact tool input), `output` (list of `{id, value, source, confidence}`), `elapsed_ms` |
| `finish` | `silk_llm_runtime.py:789-794` | `mission`, `elapsed_ms` (whole mission), `tool_calls_used`, `findings_kept`, `dropped` (list with `reason: "no valid cited datapoint_id"`), `gaps`, `summary` |
| `report_call` | `silk_ai_judge._traced_call` `silk_ai_judge.py:604-637`, event dict at `625-635` | `stage` (`"draft"`/`"revision"`/`"review"`), `timeout`, `elapsed_ms`, `success`; on failure also `error_type`, `error_message`, and when HTTP: `status_code`, `response_body` (from `silk_llm_provider.last_error()`) |
| `quality_gate` | `api.py:769-771` | `verdict`, `finding_count` |

Analyst calls appear as `llm_call` events too — the analyst runs inside a
reopened `trace_context(trace_id)` (`api.py:813-817`); writer/reviewer use
`append_event` with an explicit `trace_id` because the missions' trace context
is already closed by then (`silk_ai_judge.py:609-614`).

## 3. Symptom → cause table

Canonical source: `docs/TUNING.md` (table at lines 54-60). Reproduced with anchors:

| Symptom in trace | Most likely cause | Fix location |
|---|---|---|
| Every `tool_call.output` is empty | Tool/key/network fault, NOT a mission fault | Check the tool directly: `silk_llm_runtime.TOOLS[key]["fn"]` (registry at `silk_llm_runtime.py:289`); verify `SEARCH_API_KEY`/`COMTRADE_API_KEY` |
| Very few `llm_call` events + `finish.summary` says "غير محسوم" | Ambiguous instructions — mission doesn't know when to stop | Clarify sufficiency criteria in `silk_missions.MISSIONS[key]["instructions"]` |
| `pricing_scout`/`consumer_culture`/`channels_importers` search only in English on a non-English market | `_SEARCH_IN_MARKET_LANGUAGE` no longer appended to their instructions | `silk_missions.py:37` — verify it is still concatenated into those three missions |
| High `finish.dropped` count | Claims written without a valid `dpN` citation (drop reason `"no valid cited datapoint_id"`, `silk_llm_runtime.py:571-576`) | Sharpen instructions: every number must cite a datapoint id |
| `tool_calls_used` always equals the budget | Budget too tight for that mission | Raise `SILK_MISSION_TOOL_CALLS` (default 5, `silk_missions.py:230`) or `SILK_DEEP_MISSION_TOOL_CALLS` (default 9, `silk_missions.py:238` — applies to the six in `_DEEP_RESEARCH_MISSIONS`, `silk_missions.py:241-243`), or pass `budget={"tool_calls": N}` in a dry run |
| `llm_call` with `result="no_response (...)"` | The Claude call itself failed — read the parenthesised reason | See step 6 (failure_reason discipline) |
| Gap text mentions `SILK_RESEARCH_MAX_LLM_CALLS/_MAX_TOOL_CALLS` (`silk_llm_runtime.py:784-788`) | Global run-wide cap hit (40 LLM / 100 tool calls, checked at `silk_llm_runtime.py:709-716`) | Confirm in `budget_status`; raise the env var only with owner sign-off (cost) |

## 4. Single-mission dry run — the cheapest live diagnostic

One mission, not twelve. This is THE tuning loop (`docs/TUNING.md` steps 1-4):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 -c "
from silk_market_resolver import resolve_market
from silk_missions import deep_research

ref, _ = resolve_market('Nigeria')
out = deep_research(ref, product='تمور', hs_code='080410',
                    dry_run=True, only_agent='pricing_scout')
print(out['report'].summary)
"
```

- Entry point: `silk_missions.deep_research` (`silk_missions.py:396-449`);
  dry-run branch at `423-441`.
- Prints every trace event live to the terminal (`silk_missions.py:438-439`)
  AND writes `data/traces/dryrun-{only_agent}-{ISO3}.jsonl`
  (trace id built at `silk_missions.py:418-420`).
- Unknown mission key raises `ValueError` listing valid keys
  (`silk_missions.py:424-426`).
- Edit `silk_missions.MISSIONS[key]["instructions"]`, re-run the SAME single
  mission. Only after the mission looks right, measure full-run quality with
  `python3 -m silk_evals --case nigeria_tea` (full golden-case run — costs a
  full research; needs explicit justification).

## 5. Resume mechanics — recovering a broken run

- Every mission is checkpointed to SQLite THE MOMENT it completes:
  `silk_missions._checkpoint` (`silk_missions.py:289-299`) →
  `silk_storage.save_mission_checkpoint`. Checkpoints happen inside the
  progressive `FIRST_COMPLETED` wait loop (`silk_missions.py:363-384`),
  including timed-out missions.
- `POST /research` with `{"resume": <analysis_id>}` (`api.py:955-976`):
  - Loads `load_mission_checkpoints(id)` and re-runs ONLY missing missions
    (`run_all_missions` excludes `resume_reports` keys, `silk_missions.py:324-326`).
  - Resume of a **completed** run is a pure replay: returns the stored result,
    zero new Claude calls (`api.py:968-973`).
  - product/market/hs_code/product_card come from the stored request snapshot —
    you may resume with just `{"resume": N}`.
- `async_run=true` → 202 + `{"analysis_id", "status": "running", "poll_url"}`
  (`api.py:1038-1054`); the pipeline runs in a daemon thread
  (`_research_background`, `api.py:893-911`).
- **A redeploy kills daemon threads.** The run stays `status="running"` forever
  — this is NOT self-healing. Recovery is manual:
  `POST /research {"resume": <id>}`. Completed checkpoints are preserved.
- A sync-run crash marks the run failed and the 500 response explicitly tells
  you to resume (`api.py:1061-1072` — hint: "لا حرق اعتمادات مضاعف").

## 6. failure_reason() discipline — the PR #69 misattribution

`silk_ai_judge.failure_reason()` (`silk_ai_judge.py:68-93`):

1. If `available()` is False → "لا مفتاح كلود مُفعّل" (no key, or context-blocked
   via `silk_context.block_ai_extras`).
2. Else read `silk_llm_provider.last_error()` (`silk_llm_provider.py:30-38`,
   a contextvar set on EVERY call — reset to None at call start,
   `silk_llm_provider.py:102,133`, so stale detail can never leak) →
   "فشل نداء كلود (Type: message ...)".
3. Else generic "فشل نداء كلود (مهلة أو خطأ شبكة)".

**Rule: never accept "requires key" at face value when other Claude calls
succeeded in the same run.** The live incident behind PR #69 (commit `7dca474`):
analyst + writer timed out and the UI blamed a missing key even though 29 other
Claude calls succeeded in that same run. If `available()` is True at failure
time, the key exists — the real cause is a failed call. Locked by
`tests/test_wave_p1_ai_timeout_and_failure_reasons.py`
(`test_failure_reason_distinguishes_no_key_from_call_failure`,
`test_write_reviewed_report_call_failure_reason_does_not_blame_key`).

## 7. Contextvar traps (silent-failure class)

Agent prefs («إعدادات الوكلاء» directives), ai-extras blocking
(`block_ai_extras`), the data/LLM counter (`begin_data_counter`), tracing
(`silk_trace._active`), and `silk_llm_provider._last_error` are ALL contextvars.

- `ThreadPoolExecutor` does NOT inherit contextvars (unlike asyncio). Without a
  per-task copy, every worker thread silently sees defaults: directives ignored,
  blocking not applied, counters frozen at 0, traces empty.
- The fix pattern is in `silk_missions.run_all_missions`
  (`silk_missions.py:335-351`): a **fresh `contextvars.copy_context()` per
  submitted task** — `pool.submit(contextvars.copy_context().run, _run_one, k)`.
- ONE `Context` object cannot `.run()` from two threads at once
  (`RuntimeError: already entered`) — never hoist a single `copy_context()`
  out of the submit loop.
- Symptom checklist when a contextvar was dropped: trace file exists but has
  only main-thread events; `data_economics` shows `llm_calls: 0` despite real
  calls; a disabled agent ran anyway.
- `silk_trace.trace_context` is explicitly copy_context-compatible
  (`silk_trace.py:44-60`); code running AFTER the context closed must use
  `silk_trace.append_event(trace_id, ...)` (`silk_trace.py:99-106`) — the
  pattern used by the quality gate and `_traced_call`.

## 8. What NOT to do

- Do not re-run the full 12-mission research to test a hypothesis — use the
  dry run (step 4), report regen (`POST /analyses/{id}/report`, writer-only),
  or resume. See `.claude/skills/credit-economics/SKILL.md`.
- Do not "fix" an empty mission by loosening the citation rule — dropped
  uncited claims are the founding principle working as designed.
- Do not add prints/logs as the first move — the trace already records the
  exact prompt, every tool input/output, and every drop reason.

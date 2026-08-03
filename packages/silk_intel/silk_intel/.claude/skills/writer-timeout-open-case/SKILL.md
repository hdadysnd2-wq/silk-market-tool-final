---
name: writer-timeout-open-case
description: Case file for the UNRESOLVED deep-research report-writer failure (three production failures, PRs 69/70/71). Load before touching silk_ai_judge timeouts, the writer/reviewer, or when a /research run again produces report=None — it contains the exact evidence-reading protocol and the fixes deliberately NOT applied yet.
---

# CASE CLOSED: the report writer keeps failing — root cause found from evidence

Status: **RESOLVED** (dates/Netherlands HS080410, the 4th live failure). The
captured evidence the three prior PRs armed for finally arrived: the "Full
Report" section displayed
`empty_response: ... no text blocks — stop_reason='max_tokens'`. **Root cause:
the writer exhausted its output-token budget (`max_tokens=5000`) before emitting
any text block, so `silk_llm_provider.complete` returned `None`
(`silk_llm_provider.py:123-135`) → `report=None`.** This is exactly the branch
the evidence-capture (`last_error` `empty_response`) was built to reveal — the
`stop_reason` self-identified the phase, no guessing.

**Fix (evidence-driven, the exact `max_tokens` branch):**
- `silk_llm_provider.complete` stays a single-shot HTTP seam but now exposes
  `last_stop_reason()`; the **escalation loop lives in the writer layer**
  (`silk_ai_judge.deep_report`) so **each attempt is an independent traced call**
  — its own `report_call` event, `llm_calls` increment, and metered tokens
  (the writer tail runs outside the run-level call cap, so per-attempt visibility
  is required). On `stop_reason == "max_tokens"` the writer doubles the ceiling
  and retries, returning the fullest text obtained — `max_tokens` can no longer
  cause `report=None`. Bounded by BOTH `SILK_MAX_TOKENS_RETRIES` (3 → ≤4
  attempts) AND `SILK_MAX_TOKENS_CEILING` (16000); with defaults, doubling from
  8000 reaches the ceiling in one step, so escalation runs ≤2 attempts (retrying
  at the same ceiling is pointless). Only a pathological zero-text-at-ceiling
  still declares a gap (`None` + `empty_response`) — no fabrication.
- Writer output ceiling raised 5000 → `SILK_WRITER_MAX_TOKENS` default 8000
  (`silk_ai_judge.py`).
- Guard: `tests/test_wave_p5_writer_max_tokens_and_leaks.py`
  (`test_max_tokens_with_no_text_blocks_recovers_via_ceiling_escalation`,
  `test_deep_report_recovers_end_to_end_from_writer_max_tokens`, +
  best-partial and zero-text-declares-gap cases). Full ledger entry:
  `docs/DEEP_RESEARCH_DECISIONS.md` («القضية ٣ من البلاغ الحي — نفاد رموز
  الإخراج»).

The history and protocol below are retained for reference: the discipline that
produced this fix (three PRs of instrumentation, zero guessed fixes) is the
model to follow for the next unproven failure. Do not re-open this case for a
`max_tokens` recurrence — that is now handled; a NEW `error_type` in the
decision table (§3) is a different case.

## 1. Case history (verified against git log and code)

### PR #69 — commit `7dca474` — "Fix analyst/writer 60s timeout, false 'no key' attribution"
- **Failure**: production run (dates/Netherlands — "تمور/هولندا"). The analyst
  and writer each carry ALL 12 missions' findings in one payload; both blew the
  then-fixed 60s timeout and returned None. The UI blamed "يتطلب مفتاح كلود"
  ("requires Claude key") even though 29 other Claude calls succeeded in the
  SAME run — pure misattribution.
- **Fix**:
  - `SILK_AI_TIMEOUT_S` (default 60) stays the per-mission timeout;
    `SILK_AI_LONG_TIMEOUT_S` (default 300) added for the two heavy calls only
    — `silk_ai_judge.py:19-25` (`_TIMEOUT` line 20, `_LONG_TIMEOUT` line 25).
    Consumers: writer `silk_ai_judge.py:765-768`, analyst
    `silk_market_analyst.py:23,125`. Regular missions keep the default
    (locked by `test_regular_mission_still_uses_default_timeout_not_long_one`).
  - `failure_reason()` (`silk_ai_judge.py:68-93`) distinguishes no-key from
    actual call failure via `available()` at failure time.
  - Quality gate `analyst_layer_failed` check (`silk_quality_gate.py:190-210`):
    no report text AND all five intersections missing evidence = hard FAIL
    (`silk_quality_gate.py:264-266`) — such a run can never pass silently again.

### PR #70 — commit `8e89b06` — "Trace writer timeout path, add cheap report-regen endpoint"
- **Failure**: writer failed AGAIN (second run) with the generic
  "مهلة أو خطأ شبكة" ("timeout or network error") — no evidence whether it
  actually ran 300s or died early. Root discovery: the missions'
  `trace_context` closes when `deep_research()` returns, so analyst and
  writer/reviewer calls ran with ZERO tracing.
- **Fix**:
  - `_traced_call` (`silk_ai_judge.py:604-637`) records a `report_call` trace
    event for every writer/reviewer call: `stage` (`"draft"`/`"revision"`/
    `"review"`), `timeout`, `elapsed_ms`, `success` — via
    `silk_trace.append_event(trace_id, ...)` since no context is active.
  - The analyst is re-wrapped in a reopened `trace_context(trace_id)` in
    `api.py:813-817` (same trace file, append-only).
  - Cheap regen endpoint `POST /analyses/{id}/report` (`api.py:1296-1346`):
    ONE writer(+reviewer) call over stored mission checkpoints — rescues a $2
    run for cents and is the designated cheap reproduction harness for this bug.
  - Locked by `tests/test_wave_p2_writer_trace_regen_sanitize.py`.

### PR #71 — commit `99f5c0b` — "Capture actual writer-call exception evidence"
- **Failure**: THIRD failure, still the same generic message even with timing —
  elapsed_ms alone cannot distinguish ReadTimeout from a different exception.
- **Decision**: deliberate REFUSAL to guess between candidate fixes (widen
  timeout vs streaming vs shrink input). Instead, build evidence capture:
  - `silk_llm_provider.last_error()` contextvar (`silk_llm_provider.py:30-38`):
    set on EVERY call, success or failure; **reset to None at the first line of
    both `complete` and `complete_tools`** (`silk_llm_provider.py:102,133`) so
    stale detail can never leak between calls.
  - `_error_detail` (`silk_llm_provider.py:163-178`): exception type + message
    (`[:300]`), plus `status_code` and `response_body[:300]` for HTTP failures
    (owner explicitly asked for the response body).
  - `_timeout_pair` (`silk_llm_provider.py:90-99`): splits the single timeout
    into `(connect=min(10, t), read=t)` — so the resulting exception class
    self-identifies the phase: `ConnectTimeout` = network/DNS died in ≤10s,
    `ReadTimeout` = the model genuinely ran to the read deadline.
  - `report_call` trace events now carry `error_type`/`error_message`/
    `status_code`/`response_body` (`silk_ai_judge.py:628-635`), and
    `failure_reason()` embeds the same detail (`silk_ai_judge.py:86-92`).
  - Locked by `tests/test_wave_p3_writer_diagnostics_and_json_leak.py`.

## 2. Current state

- Unresolved: root cause of the writer failures is still unproven.
- Armed: any next failure writes `report_call` events with real exception
  evidence into `data/traces/{trace_id}.jsonl`.
- The report result carries `failure_reason` when the writer fails
  (`write_reviewed_report`, `silk_ai_judge.py:847-849`) — surfaced to the user
  instead of a fabricated report (founding principle: report is None, never
  invented text).

## 3. THE PROTOCOL for the next failure — mechanical, in order

1. **Reproduce cheaply** — never with a full /research:
   ```
   POST /analyses/{analysis_id}/report      (X-API-Key header required)
   ```
   (`api.py:1296-1346`). One writer call + up to one reviewer cycle, ~cents.
   Requires stored mission checkpoints (409 if absent). It updates the stored
   analysis and reruns the quality gate — safe to repeat.
2. **Read the trace**: open `data/traces/{trace_id}.jsonl`
   (`trace_id` = `result["deep_research"]["trace_id"]`; dir override
   `SILK_TRACE_DIR`). Filter `kind == "report_call"`. Compare `elapsed_ms`
   against `timeout` (300000ms vs 300.0s for stage `draft`/`revision`) — did it
   truly run out the clock, or die early?
3. **Branch on `error_type`** (decision table):

   | Evidence | Meaning | Direction |
   |---|---|---|
   | `ReadTimeout` with `elapsed_ms` ≈ 300000 | Payload/model latency — the call genuinely needs longer than 300s | Consider streaming responses, or raise `SILK_AI_LONG_TIMEOUT_S`, or shrink writer input — NOW justified by evidence |
   | `ConnectTimeout` (fails in ≤ ~10s) | Network/proxy/DNS problem reaching api.anthropic.com — not a Claude/payload problem | Fix infra (Railway egress, proxy); no prompt/timeout change |
   | `status_code: 529` (+ `response_body`) | Anthropic overloaded | Retry policy territory (backoff on 529), not a timeout change |
   | `status_code: 400` with a validation message | Malformed payload (e.g. oversized, bad cache_control) | Fix the request builder in `silk_llm_provider.py` |
   | `error_type: "refusal"` | Model safety-declined (`silk_llm_provider.py:118-122`) | Prompt content issue, not infra |
   | `success: true` for `draft` but final report still None/bad | Look at `review` stage events and `write_reviewed_report` cycle logic (`silk_ai_judge.py:832-866`) | Reviewer loop bug, different case |

4. **Candidate fixes already considered and deliberately NOT chosen without
   evidence** (do not apply any of them speculatively):
   - Raise `SILK_AI_LONG_TIMEOUT_S` beyond 300.
   - Streaming responses from the Anthropic API.
   - Shrink the writer input (it currently embeds all 12 missions' facts,
     `silk_ai_judge.py:655-663`, max_tokens=5000 at `silk_ai_judge.py:767`).

   **Decision rule: pick exactly the fix the captured evidence points at.**
   Tuning by guesswork already burned the owner's credits three times.
5. **Document + lock**: record the finding and the chosen fix in
   `docs/DEEP_RESEARCH_DECISIONS.md` in its existing wave-log style (Arabic,
   claim anchored to file:line, deviations declared explicitly), and add a
   regression test following the `tests/test_wave_p*.py` naming pattern
   (next free index).

## 4. Verification after ANY change in this area

```bash
python3 -m pytest tests/test_wave_p1_ai_timeout_and_failure_reasons.py \
                  tests/test_wave_p2_writer_trace_regen_sanitize.py \
                  tests/test_wave_p3_writer_diagnostics_and_json_leak.py -q
python3 -m pytest tests/ -q    # full hermetic suite before merging
```

Key locked behaviors you must not break:
- `SILK_AI_TIMEOUT_S` default 60 / `SILK_AI_LONG_TIMEOUT_S` default 300,
  env-overridable (`test_timeout_reads_from_env_var_with_default_60`,
  `test_long_timeout_defaults_to_300_and_is_env_overridable`).
- Writer/analyst pass the long timeout explicitly; ordinary missions do not.
- `last_error` reset-at-start, capture of ReadTimeout vs ConnectTimeout vs
  HTTP status+body, cleared on success
  (`test_last_error_*` in test_wave_p3).
- `failure_reason()` never blames the key when the key was present
  (`test_write_reviewed_report_call_failure_reason_does_not_blame_key`).
- `_traced_call` writes error detail into the trace
  (`test_traced_call_records_error_detail_in_trace_event`).
- Quality-gate `analyst_layer_failed` fires exactly when report text is absent
  AND all `REQUIRED_CATEGORIES` are missing (`test_quality_gate_*` in test_wave_p1).

## 5. Map of the moving parts

| Piece | Where |
|---|---|
| Timeouts `_TIMEOUT`/`_LONG_TIMEOUT` | `silk_ai_judge.py:19-25` |
| Writer call (Opus, max_tokens=5000, long timeout) | `silk_ai_judge.py:765-768` (`deep_report`) |
| Reviewer call (Haiku `_FAST_MODEL`, 30s) | `silk_ai_judge.py:816-819` (`review_report`) |
| Writer→reviewer loop, max 2 cycles, `failure_reason` on None | `silk_ai_judge.py:832-866` |
| `_traced_call` + `report_call` event | `silk_ai_judge.py:604-637` |
| HTTP seam, `_timeout_pair`, `_error_detail`, `last_error` | `silk_llm_provider.py:30-38,90-99,163-178` |
| Analyst re-wrapped in trace context | `api.py:813-817` |
| Cheap regen endpoint | `api.py:1296-1346` |
| Quality-gate hard-fail check | `silk_quality_gate.py:190-210,264-266` |

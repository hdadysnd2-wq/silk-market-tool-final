---
name: credit-economics
description: How to work on this system without burning the owner's paid credits — the cost map of /research, the cheap-first iteration ladder, and the exact semantics of the daily cap and Comtrade budget. Load before ANY action that could trigger a live Claude or paid-provider call, and whenever planning a debugging or tuning session.
---

# Credit economics — the owner has already burned real money on unsatisfying runs

A full `/research` run costs **~$2** (owner-confirmed, live Railway numbers). Tuning
sessions have already burned credits with no satisfying results. The house standard:
**every live call must be justified by what the free layers could not tell you.**

## 1. The cost map of one /research run

| Component | Model | Budget | Where set |
|---|---|---|---|
| 12 missions | Opus (`SILK_AI_MODEL`, default `claude-opus-4-8` — `silk_ai_judge.py:19`) | `tool_calls=5` default, 9 for the six deep missions; `max_output_tokens=4000` (`silk_missions.py:229-250`, env `SILK_MISSION_TOOL_CALLS`) | `silk_missions.py` `_MISSION_BUDGET` / `_DEEP_RESEARCH_MISSION_BUDGET` |
| Analyst | Opus, payload = ALL 12 missions' findings | one call, `SILK_AI_LONG_TIMEOUT_S=300` | `silk_market_analyst.py` |
| Writer + revision | Opus, `max_tokens=5000`, long timeout | up to 2 write cycles (`write_reviewed_report`, `silk_ai_judge.py:832`) | `silk_ai_judge.deep_report` (`silk_ai_judge.py:640`) |
| Reviewer, extractors, entity filters | Haiku (`SILK_AI_FAST_MODEL`, `silk_ai_judge.py:98`) | cheap; 12–30s timeouts | throughout `silk_ai_judge.py` |
| Run-level hard caps | — | `SILK_RESEARCH_MAX_LLM_CALLS=40`, `SILK_RESEARCH_MAX_TOOL_CALLS=100`, graceful finish + `deep_research.budget_status` | `silk_llm_runtime._run_loop` (~`silk_llm_runtime.py:709-716`), `api.py:741` |

Pricing arithmetic lives in `silk_pricing.py`: opus-4-8 $5/$25 per MTok in/out,
haiku-4-5 $1/$5, cache read ×0.1, cache creation ×1.25; unknown models land in
`unpriced_models` and are **never silently zeroed**. Prompt caching (PR #68,
`silk_llm_provider.py` `cache_control` on the system block + last tool definition,
`silk_llm_runtime._mark_cache_boundary` per round) makes multi-round missions much
cheaper than naive math suggests — do not "optimize" it away.

Read `result["data_economics"]` after every run (`silk_context.begin_data_counter`,
`silk_context.py:105+`): store/cache/live counts and per-model token usage. A warm
fact store makes /analyze runs near-free — that is the point of store-first serving.

## 2. The cheap-first ladder — mechanical, no exceptions

Work DOWN this ladder; each rung requires the rung above to be insufficient:

0. **Hermetic tests** — free, offline, ~5s. `python3 -m pytest tests/ -q`.
   Covers all logic, parsing, rendering, guard behavior. Most "is my fix right?"
   questions end here.
1. **Single-mission dry run** — cost of ONE mission, not twelve:
   `deep_research(ref, product=..., hs_code=..., dry_run=True, only_agent="pricing_scout")`
   (`silk_missions.py:396+`). Prints the full trace live, writes
   `data/traces/dryrun-<mission>-<ISO3>.jsonl`.
2. **Report regen** — cost of one writer call ("cents not dollars"):
   `POST /analyses/{id}/report` (`api.py:1296`) rebuilds the written report from
   saved mission checkpoints. THE way to test any writer/reviewer/prompt/render
   change against real data.
3. **Resume of a partial run** — only missing missions re-run:
   `POST /research` with `resume=<analysis_id>`. Resuming a COMPLETED run is a
   pure replay with **zero** Claude calls (`api.py:955-976`).
4. **Full /research** — last resort (~$2). Requires an explicit reason the
   ladder above could not provide: e.g. measuring a mission-prompt change with
   `python3 -m silk_evals --case <key>` after the cheap loop already passed.

Hard rule: **never re-run a full research to test a render, writer, report-structure,
or sanitization change.** Rungs 0 and 2 cover all of those completely.

## 3. Daily-cap semantics (SILK_PAID_DAILY_CAP) — know before you spend

Enforced by `silk_usage.try_reserve_paid_calls` (`silk_usage.py:118`):

- **Atomic**: `BEGIN IMMEDIATE` write-lock-before-read, single transaction — no TOCTOU.
- **Fail-closed**: ANY DB error refuses the spend (a corrupt `usage.db` once meant
  unlimited paid spend — security fix M-2; never "fix" an error branch to allow).
- **Never refunded**: a reservation is consumed even if the run then fails.
  `/deepen` reserves per requested paid flag BEFORE agents run (`_guard_paid`,
  `api.py:427`); the free path reserves exactly **1** activation per request that
  will use Claude (`_free_ai_extras_allowed`, `api.py:481`). A crashed run still
  spent its reservation — budget for retries accordingly, and prefer `resume`
  (which does NOT re-reserve for completed missions).
- Exhaustion behavior differs by path: `/analyze` **degrades** with
  `ai_extras_note` (never 429); `/research` gets a **409** from
  `_research_readiness` (`api.py:504`) because Claude is a run requirement there;
  `/deepen` gets 429. `would_exceed_cap` (`silk_usage.py:105`) is the read-only
  precheck — it never charges.
- The counter lives in its own `usage.db` (`SILK_USAGE_DB` / `SILK_DATA_DIR`),
  keyed by ISO date, deliberately never in `silk.db`.

## 4. Comtrade budget — the other metered resource

- `COMTRADE_DAILY_BUDGET`: default **450 with a key, 4 without**
  (`silk_collectors.py:63-77`). Spend is computed from `collection_runs`
  SUM(fetched+failed) — **failed attempts count**, because Comtrade bills actual
  calls (project-review fix; do not "optimize" the counter to targets).
- The refresh scheduler pre-warms recent HS codes × priority markets but stops
  when remaining budget ≤ `SILK_REFRESH_BUDGET_RESERVE` (default 150) so
  interactive requests keep headroom.
- Warm-store serving is the main cost saver: `market_imports_cached`
  (`silk_data_layer_v2.py:274`) serves stores hits instantly (stale ones flagged
  `status="stale"` with a background refresh). Killing SWR (`SILK_SWR=0`) trades
  freshness for zero background spend.

## 5. Session budget checklist (run before any live work)

1. `GET /health` → sources status, `research_ready`, warnings.
2. `GET /sources` → which providers are configured (flags need the API key).
3. Check today's headroom: cap counter is in `usage.db`; Comtrade spend via
   `collection_runs`. A `/research` 409 naming the cap means the day is spent.
4. State your plan in ladder terms ("rung 2: one regen call") before executing.
5. After the run: read `data_economics` and `deep_research.budget_status`; if a
   cap was hit mid-run the output declares it — treat that as data, not noise.

## 6. What NOT to do

- Do not disable or raise `SILK_PAID_DAILY_CAP` to "get past" a 429/409 while
  debugging — reproduce on the cheap ladder instead.
- Do not call `GET /diagnostics` repeatedly: it fires LIVE probes with the
  server's keys (auth + rate-limited for exactly this reason, `api.py:1152`).
- Do not loop `/research` retries on failure — that is the pre-PR-#65 double-burn
  incident. Use `resume`, which skips completed missions.
- Do not add an automatic fallback LLM provider at cap exhaustion — settled owner
  decision: a declared stop is the correct design (`docs/VISION.md` §9.5).

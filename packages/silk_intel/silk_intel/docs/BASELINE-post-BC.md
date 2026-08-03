# BASELINE — post-B/C (re-measured for Part E)

> **Decision D-04.** Commands #2–#5 (UI, assembly, merchant language, scraper)
> legitimately shifted the baseline, so Part E (cost & speed) re-measures here
> instead of against the frozen `docs/BASELINE-2026-07-16.md`. The ≤ $1.5 /
> < 10 min targets (D-01: the $1.5 target is measured **only after** E) are
> judged against this file.
>
> **Provenance (Lessons 1 & 10).** `[repo-measured]` = reproduced here;
> `[owner-verified]` = a live paid `/research` run the owner prints (no
> `ANTHROPIC_API_KEY`/paid egress in CI, so end-to-end cost/runtime cannot be
> reproduced offline). Nothing guessed.

Measured at the Command #6 commit (E1–E3), on top of Commands #1–#5b.

---

## 1. Test suite — `[repo-measured]`

```
python3 -m pytest tests/ -q
→ 1098 passed, 2 skipped
```

Regression floor for the final acceptance run.

---

## 2. Cost levers now in the code (what changed since `BASELINE-2026-07-16.md`)

| Lever | Original baseline | Now | Where |
|---|---|---|---|
| Review cycles | default **2**, cycle 2 on *any* issue | default **1** (`SILK_MAX_REVIEW_CYCLES`, cap 2); cycle-2 rewrite **only on blocking** | `silk_ai_judge._max_review_cycles`, loop `:1206-1225` (E1, landed #107; jargon-blocking from B2 feeds it) |
| Mission model | **Opus** for all 12 missions | **Haiku** (`_MISSION_MODEL`, `SILK_MISSION_MODEL` to override); analyst + writer stay **Opus** | `silk_llm_runtime._MISSION_MODEL`, `run_llm_agent(model=…)`; `silk_market_analyst` passes `_SMART_MODEL` (E2) |
| Reviewer model | Haiku | Haiku (unchanged) | `silk_ai_judge.review_report` |
| Per-stage `max_tokens` | present | present (missions 4000, analyst 1800, reviewer 900, writer escalates) | unchanged |
| Prompt caching | on (`cache_control: ephemeral`) | on (unchanged) | `silk_llm_provider`, `silk_llm_runtime._mark_cache*` |
| Retry storms | already bounded | bounded (unchanged) | `silk_ai_judge:37,995`; runtime round cap |

**Expected effect (to be confirmed live):** the biggest single lever is routing
the 12 missions off Opus (5/25 per 1M) onto Haiku (1/5 per 1M) — roughly a 5×
cut on the mission portion — plus review cycle 2 no longer firing on cosmetic
issues. Both push toward the ≤ $1.5 target. Cost split is visible per-model in
`data_economics.cost_usd_by_model` and per-mission in `cost_usd_by_mission`.

`cost_usd_estimate` / `≤ $1.5` — **`[owner-verified]`**, printed from a live run.

---

## 3. Speed instrumentation (E3) — `[repo-measured]` shape, `[owner-verified]` numbers

New per-stage wall-time profile in `data_economics` (`api._run_research_pipeline`):

- `stage_seconds`: `{missions, analyst, synthesis, writer}` (seconds).
- `stage_total_seconds`: sum.
- `stage_top_sinks`: the 3 largest, labeled (البعثات المتوازية / المحلل / التوليف / الكاتب+المراجع).

Hermetic-run shape (mocked model calls, so numbers are ~0 — proves the wiring):
```
stage_seconds: {"missions": 0.2, "analyst": 0.0, "synthesis": 0.0, "writer": 0.0}
stage_top_sinks: [{"stage":"البعثات (متوازية)","seconds":0.2}, …]
```

Concurrency (already in place): the 11 core missions run in a
`ThreadPoolExecutor` (`silk_missions.run_all_missions`), mission 12 sequential
after them; the analyst→synthesis→writer tail is sequential. The scrape job is
fully decoupled (D-02) and does not add to runtime.

`stage_total_seconds` / `< 10 min` — **`[owner-verified]`**, printed from a live run.

---

## 4. What the owner prints on the final acceptance run

One fresh live `/research` (dates × a real market) with the current env, then:

```bash
curl -sS "$BASE/analyses/$ID" -H "$(H)" | python3 -c "
import sys,json; e=json.load(sys.stdin).get('data_economics',{})
print('cost_usd_estimate:', e.get('cost_usd_estimate'))     # target ≤ 1.5
print('by_model:', e.get('cost_usd_by_model'))               # Opus vs Haiku split
print('stage_total_seconds:', e.get('stage_total_seconds'))  # target < 600
print('top sinks:', e.get('stage_top_sinks'))
"
```

If cost > $1.5 or runtime > 10 min, the `by_model` / `stage_top_sinks` lines
name exactly where to cut next — no guessing.

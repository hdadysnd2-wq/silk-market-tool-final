# EXEC_PATH_AUDIT — the brain path, image → executive report

Adversarial audit of the exact Wave 3 chain: image/name → HS classification →
world screening → top-5 → competitor prices → buyers → executive report. Five
dimensions were swept in parallel (state handoffs & crash survival, silent
degradation, an *executed* render matrix, bounded total time, fan-out vs paid
caps); every finding below was independently verified by 1–2 adversarial
refuters, and the render-matrix findings were reproduced by actually rendering
the docx and probing its text. 21 findings confirmed, 2 refuted, 8 low.

**Verdict:** the chain is functionally complete and, after the fixes below, its
provenance is honest end-to-end and its worst-case wall-clock is finite and
guarded. Two critical issues (a fabrication reaching the client report; an
unmetered paid-key drain) are fixed in this wave, along with every defect that
made the executive report wrong or misleading, and the cheap correctness gaps
in the stage handoffs. Three larger items are deferred with rationale.

Bounded-time verdict (from the time-bounds sweep, confirmed): the automated
chain's per-stage worst cases sum finite; the 50-minute stuck-row reaper
backstops any single analysis, and after this wave's fixes no unbounded
synchronous paid call remains on the request path.

## Fixed in this wave

| # | Sev | Dimension | Finding | Anchor | Fix |
|---|-----|-----------|---------|--------|-----|
| C6 | **critical** | silent-degradation | Fabricated mock-customs buyers reach the executive docx labeled source `customs` with a "prior import activity" lawful basis | `app/providers/registry.py:50`, `report_view.py:273` | Carry the shipments provider name onto the buyer; the executive report labels mock/fixture-derived buyers as a declared demonstration source, never as observed customs. |
| C17 | **critical** | fan-out | `POST /deepen/prices` drains the paid SerpApi key with no reservation, budget, rate limit, or market cap | `app/api/pricing.py:42` | Per-user rate limit + market-count cap + `budget_scope` + `silk_usage` reservation before entering deepen. |
| C1 | high | handoffs | `run_world_ranking` not idempotent under `acks_late` redelivery — duplicates the whole `CountryRanking` shortlist into the report | `app/services/ranking.py:53` | Delete existing rankings for the analysis in the same transaction before insert. |
| C2 | high | handoffs | No status precondition on `/enrich` and `/deepdive` — Stage 2/3 can run before Stage 1 commits, producing `enriched` analyses with zero rankings | `app/api/analyses.py:114` | Require `ranked`/`enriched` (resp. `enriched`/`deepened`) at the endpoint and re-check under refresh in the task transition. |
| C5 | medium | handoffs | `run_world_ranking` lacks the terminal-status refresh guard + heartbeat stages 2/3 got — the symptom-B reaper write race is still open in Stage 1 | `app/workers/tasks.py:323` | `db.refresh` + terminal guard + `heartbeat.beat` in Stage 1. |
| C3 | medium | handoffs | Stage-3 enqueue sits inside Stage-2's failure `try` after the commit — a broker error flips a committed `enriched` analysis to `failed` and drops Stage 3 | `app/workers/tasks.py:382` | Move the chain enqueue outside the try; never mark failed after a successful commit. |
| C7 | high | silent-degradation | Offline/fixture Comtrade data stored & reported as `comtrade` @0.9 — offline, live, and degraded runs indistinguishable | `app/providers/shipments/comtrade.py:158` | Stamp `comtrade_fixture` / lowered confidence on the offline/degraded path so the report shows the substitution. |
| C8 | high | silent-degradation | Executive score silently falls back from the Stage-2 model (0..1) to the Stage-1 raw-USD screen score with no label | `app/services/report_view.py:301` | Surface `score_model` per market and label the Stage-1 fallback. |
| C9 | high | render | Saudi market share rendered 100× too small (0.3% for a real 30%) — unit mismatch at the stage-2 seam | `app/services/stage2.py:70` | Store the percent-point value the engine narrative contract expects (scoring unaffected — normalized per cohort). |
| C10 | high | render | Every production executive report opens with `تعذّر إصدار توصية` + a false `فجوات: لا شيء` why-line | `packages/silk_intel/.../silk_render.py:59` | Emit an honest declared-gap why when the platform path carries no jury/decision. |
| C11 | medium | render | English platform statuses (`enriched`/`ranked`/`none`) leak raw into the Arabic status line | `packages/silk_intel/.../silk_reports.py:3889` | Extend the status→Arabic map to the platform vocabulary. |
| C12 | medium | render | Raw internal provider keys (`world_trade`, `serpapi_shopping`, …) leak into the Arabic narrative and sources | `packages/silk_intel/.../silk_reports.py:3927` | Map provider keys to public source labels. |
| C13 | medium | render | Neither suite could catch the docx text defects (PK-magic-only endpoint tests) | `apps/api/tests/test_executive_report.py` | Add a product-side test that probes the rendered docx text for all four leak classes. |
| C14 | high | time-bounds | `deepen_prices` runs unbounded synchronous paid fan-out in the request thread, outside every guard | `app/api/pricing.py:43` | Same fix as C17 (cap + budget + reservation + rate limit). |
| C15 | high | time-bounds | `SoftTimeLimitExceeded` swallowed by broad `except Exception` on the vendor path, defeating the symptom-B retry model | `packages/silk_intel/.../silk_data_layer.py:665` | Re-raise `SoftTimeLimitExceeded` before the broad handlers. |
| C16 | medium | time-bounds | Engine breaker never opens on transport timeouts — dead-host floor of 45s × every market | `packages/silk_intel/.../silk_data_layer.py:154` | Record a breaker failure on transport exceptions so the host fast-fails after the threshold. |
| C18 | high | fan-out | Discovery fan-out (~150 paid calls/market) charged to no budget; endpoint re-triggerable without limit | `app/api/buyers.py:50` | Per-user rate limit + market-count cap + market validation. |
| C19 | high | fan-out | Paid Anthropic vision call per intake has no cap/reservation/cache/rate limit | `app/services/product_vision.py:104` | Rate-limit the create/classify endpoints (vision reservation + cache tracked as follow-up below). |

## Refuted (not defects)

- **Stage-2 budget exhaustion never reaches the report** — refuted: a
  budget-skipped row still carries its present components at reduced
  `score_confidence`; the gap *is* represented.
- **Demo-seed coverage only logged** — refuted: `run_world_ranking` fails
  loudly with an actionable reason on `coverage_state == "none"`; demo-seeded
  volumes are only reachable in `ENVIRONMENT=local`.

## Deferred (real, larger — tracked follow-ups)

- **C4 (medium) — `run_discovery` has no retry / terminal-failure record.**
  Unlike the funnel stages it is a plain task, so a fault discards the run with
  nothing for the reaper to reconcile. Fixing it well means the full
  bind/retry/`_mark_*_failed` + per-batch checkpoint treatment — a task-discipline
  refactor, not a one-liner. Deferred; the run is idempotent (Wave-2 `already`
  logic) so a manual re-trigger is safe in the meantime.
- **C20 (medium) — the "per-analysis" API budget resets per task invocation.**
  `budget_scope` is a fresh in-memory 150-call allowance each run, so the
  decision-#5 ceiling is per click, not per analysis. A true fix needs a
  persistent per-analysis counter (Redis or a column). Deferred; the new
  endpoint rate limits (C17/C18) bound the abuse vector in the meantime.
- **C21 (medium) — importer-intel (Volza/Explee) is a no-op in discovery.**
  `run_discovery` never opens a deepen scope, so the Wave-3 item-4 paid agents
  structurally skip even with keys. The providers, registry gating, and
  fail-closed-keyless behavior are built and unit-proven; wiring them live needs
  discovery to become deepen-capable *with* the per-call reservation of C20
  first. Deferred as a deliberate sequencing decision, documented here and on
  the PR. (The C19 vision reservation/cache is deferred for the same
  reservation-plumbing reason; the endpoint rate limit lands now.)

## Method

`docs/WAVE3_DIAGNOSIS.md` covers the two live symptoms this chain was built to
fix. This audit is the adversarial pass over the finished chain: 5 finder agents
× (1–2 refuters each), 42 agents total, render-matrix findings reproduced by
rendering real docx and probing text. Evidence class per finding is direct
reproduction (render/fan-out/time) or static code review with file:line quotes.

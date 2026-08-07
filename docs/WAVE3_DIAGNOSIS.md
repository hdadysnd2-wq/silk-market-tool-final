# Wave 3 — diagnosis of the two live production symptoms

Written BEFORE implementation (mission rule). Both symptoms were reproduced /
traced at file:line against the current tree; fixes in this wave target these
mechanisms, not assumptions.

## Symptom A — "HS classification fails outright on real products"

**Root cause: the product is wired to the engine's weaker, offline classifier
only.** `apps/api` reaches HS classification exclusively through
`app/services/engine.py:47 resolve_hs_candidates()` →
`silk_hs_resolver.resolve_all()` — a pure CSV + `difflib` name matcher with two
kill-gates:

1. `silk_hs_resolver.py:163` — hard `score < 0.7 → value=None`; scoring
   (`:124-135`) treats the whole query as ONE token, so any realistic name
   (brand, pack size, Arabic compound) drives the `SequenceMatcher` ratio to
   ~0.3–0.5.
2. `silk_hs_resolver.py:187-200` — `silk_hs_confirm.confirm_hs` term-overlap
   gate (`_DEFAULT_MIN_OVERLAP = 0.5`): every extra word enlarges the
   denominator, so "Al Munawara Premium Sukkari Dates 1kg" fails on the
   CORRECT code 080410 at overlap 0.33.

Reproduced offline: **8 of 10 realistic product names → `classification_status
= "failed"` with `hs_candidates = []`** ("abaya" best-matches *bakery
products* at 0.55). Generic seed nouns pass; anything a factory actually types
fails.

Aggravators:
- Vision output makes it WORSE: `hs_classifier.py:102-103` appends the vision
  description into the query, which lowers both gates' scores (reproduced:
  enriched query fails where bare name passes). The image never influences HS
  at all.
- The failure is silent-by-design: null envelopes are dropped
  (`hs_classifier.py:111-127`), the task returns SUCCESS, the user gets a dead
  end with zero candidates — not even a picker.

**The fix already exists inside the engine and is referenced nowhere in
`apps/`:** `silk_hs_classifier.classify_general` (`silk_hs_classifier.py:398`)
classifies with Claude over the FULL WCO nomenclature (01–97, not the 5.6k-row
seed), validates every candidate through a deterministic no-fabrication gate
(`_validated_candidate`, `:301-346`), reserves spend atomically inside the
module (`_reserve_llm_call` → `silk_usage.try_reserve_paid_calls` +
`SILK_PAID_DAILY_CAP`), caches results, and **degrades honestly keyless**:
`allow_claude=False` returns `tier="manual"` with 8–9 real seed candidates —
strictly better than today's empty list. The resolver's own rejection note
(`silk_hs_resolver.py:197`) literally says "صنِّف عبر المصنّف العام" (classify
via the general classifier) — pointing at the function the platform never
calls.

**Fix (item 1):** export `classify_general` (and `needs_classifier`) through
the `app/services/engine.py` seam; resolver stays as the free first pass,
escalation on miss; bare-name query first (description enrichment demoted);
`tier="manual"` candidates surfaced to the picker instead of `[]`;
CSV fallback flagged in provenance. Optionally (additive) export
`silk_product_intake.intake_image` so the photo can feed
`ingredients`/`category` into the classifier.

**NOT the root cause:** the mission's staleness pointer. Upstream commit
`59fbb26` (P5: Claude judge on main path, latest-year, Serper alias) exists
only on upstream branch `claude/project-review-nf66l4` (never merged to
upstream main) — and its full content is ALREADY in the vendored tree
(`silk_websearch_agent.py:28-36` SERPER alias, `silk_engine.py:25-35`
`_default_year = today-1`, `api.py:1032` with_ai main path,
`tests/test_p5_judge_and_reach.py`). The vendored engine is strictly NEWER
than upstream main on every sampled brain-path file. Nothing to port; symptom
A is a **product-side wiring gap**, not engine staleness.

## Symptom B — "Analyses run a very long time, then return an error"

Ranked root causes (all traced; #1–#2 are certainties, and together they ARE
the reported symptom):

1. **`world_trade` is structurally empty in production, so every analysis
   fails in <1s with an unreachable remedy.**
   - demo seed is local-only (`seeds/seed.py:290-296`; deploy sets
     `ENVIRONMENT=production`),
   - the sync task fail-closes on `COMTRADE_OFFLINE=1` / missing key
     (`tasks.py:641-643`; `deploy-to-railway.sh:280` sets it),
   - and even WITH a key, `sync_world_trade` does `from etl import
     world_trade_sync` — but `etl/` is not in the production image
     (`apps/api/Dockerfile:27,41`) → permanent `ImportError` →
     `"etl environment unavailable"`.
   `coverage_state` (`world_funnel.py:99-116`) can never leave `"none"`; the
   persisted failure text promises "a coverage sync has been requested —
   please retry in a few minutes" — a promise that can never come true.

2. **The funnel UI treats `failed` as "keep polling"** —
   `WorldFunnel.tsx:65-72` and `:102-105` poll until `ranked|enriched` only,
   so a sub-second failure spins for `LIVE_SCREEN_TIMEOUT_MS = 180_000` and
   then renders the raw `pollUntil: timed out after 180000ms`
   (`lib/poll.ts:26-28`, `WorldFunnel.tsx:140`). `failure_reason` is on the
   wire (`schemas/analysis.py:63`) and never displayed. **This is the exact
   "long wait then generic error" the user reports.**

3. **`SoftTimeLimitExceeded` is misclassified as permanent with an empty
   message** — it is not a `TimeoutError` subclass (`billiard/exceptions.py`),
   so `_is_transient` (`tasks.py:41-46`) says permanent and the persisted
   reason is the truncated `"stage2_enrich: SoftTimeLimitExceeded: "`.

4. **Reaper vs retry-budget conflict:** worst-case stage wall-clock is
   4 × 600s + 35s ≈ **40.6 min**, but `reconcile_stuck_analyses` fails
   anything not updated for 30 min (`config.py:151`) — and NO stage bumps
   `Analysis.updated_at` mid-run (stage2/3 write only `CountryRanking` rows).
   A legitimately long run is killed with "stalled in 'ranked'… please
   re-run", and the still-running worker can then overwrite the `failed`
   status with no guard (write race).

5. **Hard-limit kill → redelivery loop:** a 660s SIGKILL bypasses
   `_mark_analysis_failed`, and `task_reject_on_worker_lost=True` requeues —
   unbounded, currently masked only because `etl/` (whose
   `comtradeapicall.getFinalData` at `etl/world_trade_sync.py:233-246` has NO
   timeout) is absent from the image.

6. `silk_tariffs_agent.py:151` bypasses the engine's circuit breaker (raw
   `requests.get`, 30s × 20 markets = 10-min silent floor in Stage 2).

**Fix mapping in this wave:** item 2 (world screening via the engine ranker +
a production-reachable coverage path), a dedicated symptom-B commit
(UI failed-state handling + per-stage progress stamps, SoftTimeLimitExceeded
classified transient-with-bound, reaper window > retry worst-case + status
guard, tariff-agent breaker routing, timeout on the etl fetch), and item 8's
audit re-verifies the whole chain end-to-end with a regression test for this
exact scenario.

# ADR-0007 — Bridge the engine's deep-research pipeline as an opt-in Top-5 report

- **Status:** Accepted
- **Date:** 2026-08-07
- **Deciders:** Owner
- **Relates to:** engine `/research` (12-mission deep research) · locked decision #2
  (engine imported in-process) / #5 (budget scope) / #7 (one render seam) ·
  invariants I1 (no fabrication) / I5 (paid = deepen-gated) · audit C3 (fail-closed)

## Context

The engine (`packages/silk_intel`) owns a second, far deeper pipeline than the
world funnel: `silk_missions.deep_research` runs **12 Claude research missions**
per market (trade, economy, competition, regulatory, risk, pricing, channels,
consumer culture, dynamics, opportunity gaps, …), each a tool-using agent that
returns sourced `DataPoint` findings, then an analyst + synthesis verdict. It is
the "deep research" behind the engine's `/research` endpoint.

The product today ships two keyless reports off the funnel: the full docx
(`build_engine_result`) and the **executive multi-market report**
(`build_executive_result`) — both are pure Postgres reads, always available, no
API key required. The deep-research pipeline is **paid** (Claude, 12 missions ×
each Top-5 market) and slow, so it cannot be the default. But factories want it
for the shortlisted markets.

## Decision

**Bridge the engine's deep-research pipeline into the product as a separate,
OPT-IN, KEY-GATED "Deep research report (Top 5)", DISTINCT from — and additive
to — the always-available, keyless funnel executive report (which stays the
default).**

- The default deliverable is unchanged: the funnel executive report remains
  keyless and is not touched by this work.
- The deep-research report is triggered on demand (its own worker task + poll +
  download), runs the engine's deep research for each of the product's persisted
  Top-5 `CountryRanking` markets, and renders ONE combined factory-facing docx.
- It is **fail-closed without `ANTHROPIC_API_KEY`** (I5 / audit C3): the single
  engine seam `engine.run_deep_research` returns `None` when no key is configured
  and **makes zero paid calls** — the engine mission runner is never invoked. In
  that state the report is still produced, but as a declared-gap document that
  says "deep research pending API key" (I1) — never a fabricated narrative.
- Every paid run happens inside `engine.deepen_scope(True)` **and** an
  `api_budget.budget_scope` (I5 + decision #5): the deepen contextvar re-arms the
  engine's paid agents for the block only, and the budget scope caps/logs spend.
- The engine stays the single research brain; the product composes the engine's
  sourced findings into the client-facing combined docx (the same product-side
  composition pattern the executive report already uses), reading ONLY from the
  deep-research output — never the funnel/analyze template — so the two report
  types never blur.

## Cost shape

Cost scales as **12 missions × N Top-5 markets** of Claude tool-use per run
(≈ up to 60 mission passes plus a synthesis verdict per market). This is why it
is opt-in and gated, not part of the default report. The engine's own
per-analysis LLM/tool ceilings (`SILK_RESEARCH_MAX_LLM_CALLS` /
`SILK_RESEARCH_EXPECTED_USD`) still apply inside each market's run, and the
product-side `budget_scope` bounds/logs the live-call fan-out per report.

## Keys / decisions the owner must provide

1. `ANTHROPIC_API_KEY` — already the platform LLM key (LAUNCH_KEYS §1). With it
   set, the deep-research report runs; without it the slot stays fail-closed
   with a declared-gap "pending API key" document. No NEW key is required — this
   report reuses the existing Anthropic key and is gated on it.
2. Confirm the opt-in cost posture: each report spends real Claude budget across
   up to 5 markets × 12 missions. It is behind an explicit user action, never
   auto-run by the funnel.
3. (Optional depth) the engine's paid data agents (`LOCALPRICE_API_KEY`,
   `VOLZA_API_KEY`, `EXPLEE_API_KEY`) enrich mission findings when present; each
   stays deepen-gated and fail-closed on its own key (unchanged by this ADR).

## Consequences

- Keyless production and the offline test suite see the deep-research report as a
  declared-gap "pending API key" document — zero paid calls, zero fabrication,
  test-locked.
- A new pollable status lives on `Product` (`research_status` +
  `research_report_key`, migration 0022) so the trigger→poll→download flow reaches
  a terminal state like the other pipeline tasks.
- The funnel executive report is completely unchanged; this is purely additive.
- Rendering the combined multi-market document is done product-side (python-docx)
  by composing the engine's per-market deep-research findings, each keeping its
  engine `DataPoint` source label. Reusing the engine's single-market `/research`
  docx renderer plus a multi-document merge was considered and deferred: the
  engine renderer is single-market and docx-merge is fragile, whereas product-side
  composition is the already-accepted executive-report pattern (decision #7).

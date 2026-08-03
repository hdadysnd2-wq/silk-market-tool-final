---
name: architecture-map
description: The mental model of this repo — two pipelines on one spine, the naming traps that cost days (silk_research vs /research, data layer v1 vs v2, silk_storage vs silk_store), storage topology, and the governance-docs reading order. Load first when orienting on any task that spans more than one module.
---

# Architecture map — two pipelines, one spine, four naming traps

## 1. The two pipelines

**Pipeline 1 — `/analyze`** (`silk_engine.analyze()`, `silk_engine.py:41`). Order is
load-bearing; stages communicate ONLY by mutating the top-`_ENRICH_TOP=3`
(`silk_engine.py:38`) ranked-row dicts in place:

1. **Resolve** product → HS6 (`silk_hs_resolver`; difflib, weak match < 0.7 ⇒
   `None` with the best-candidate note, `silk_hs_resolver.py:142`; chapter-27
   exclusion gate `EXCLUDED_HS_CHAPTERS`, `silk_hs_resolver.py:53`). An explicit
   `hs_code` arg bypasses the resolver (discovery hand-off) but not the exclusion.
2. **Rank** ~38 markets on 4 weighted components (`silk_market_ranker.WEIGHTS`,
   `silk_market_ranker.py:116`; missing components renormalize, confidence =
   present/4; year fallback walks back ≤ `_MAX_YEAR_FALLBACK=4`,
   `silk_market_ranker.py:218`).
3. **Core agents** per top market (TradeFlow/Economic/Competition via
   `ResearchManager`) — reports HELD in `reports_by_iso`, jury deliberately
   deferred.
4. **Enrichment layers** (`with_*` flags) mutate `row["trends"/"tariff"/
   "localprice"/"channels"/...]`; exceptions become `_enrich_error_dp`
   (`silk_engine.py:307`); NEVER change `total_score`.
5. **Correlation** (`correlation.py`, only with a `product_card`) reads those
   exact string keys — renaming an enrichment key silently empties threads.
   Zero external calls (AST-enforced); Dice-coefficient name matching,
   `_MATCH_THRESHOLD = 0.5` (`correlation.py:31`).
6. **Synthesis** (`silk_synthesis.synthesize`, `silk_synthesis.py:90`) — the ONLY
   verdict entry; stage 1 deterministic jury, stage 2 Claude (confrontation
   prompt when correlation threads exist). The jury is deferred to here so
   stage 2 sees the threads — do not "simplify" the ordering.
7. **View** (`silk_render.build_view`, `silk_render.py:695`) — the ONE view-model
   every surface derives from.

**Pipeline 2 — `/research`** (waves 6–13; NOT documented in CLAUDE.md — the
current reference is `docs/ARCHITECTURE.md`): 12 Claude tool-use missions
(`silk_missions.MISSIONS`) run in parallel with per-task
`contextvars.copy_context()` → analyst builds exactly 5 intersections
(`silk_market_analyst.py`) → writer/reviewer loop (`silk_ai_judge.deep_report` /
`write_reviewed_report`) → same `synthesize()` and `build_view()`. Per-mission
SQLite checkpoints + `resume=`, JSONL traces in `data/traces/`, deterministic
quality gate, `async_run` background mode. Claude is a run REQUIREMENT here
(409 preflight), unlike `/analyze` where it is optional garnish.

## 2. The naming traps (each cost real time — read twice)

| Trap | Truth |
|---|---|
| `silk_research.py` ≠ `/research` | `silk_research.py` is the OLDER deterministic 8-agent Stage-3 pack running INSIDE `/analyze` via the `with_research` flag, feeding `silk_decision.decide()` (weighted 5-pillar engine, option A 30/25/20/25, GO≥0.65 / NO-GO<0.45, `SILK_DECISION_WEIGHTS=B` switch). Its output is `row["research"]` + `row["decision"]`. The 12-mission system's output is `view["deep_research"]` — deliberately different name (`docs/DEEP_RESEARCH_DECISIONS.md` Decision 4). |
| `silk_data_layer_v2.py` ≠ a replacement for v1 | v1 = primitives (DataPoint, throttled HTTP session, `comtrade_trade`, `world_bank`, M49↔ISO3). v2 = DERIVED indicators built ON v1 (`market_imports`, `mirror_saudi_export`, `ppp_per_capita`) plus the store-first/SWR machinery (`market_imports_cached`, `silk_data_layer_v2.py:274`). Both are live; agents import from both. |
| `silk_storage.py` ≠ `silk_store.py` | `silk_storage.py` = analyses blobs + research_missions in `data/silk.db` (legacy additive-ALTER migrations). `silk_store.py` = fact store + settings in `data/silk_store.db` (`migrations/NNN_*.sql`). Duplicate-looking function names exist in both — api.py uses silk_storage for analyses and silk_store for facts/settings. Don't mix. |
| Two "verdict" engines | `JuryCommittee` (stage 1) + Claude stage 2 live in synthesis; `silk_decision` is a VIEW-level override (a valid `row["decision"]` replaces the jury line in `build_view` and demotes jury to a data-sufficiency line). Guard test: `test_single_authoritative_verdict_everywhere`. There is still only ONE synthesis path. |

## 3. Storage topology

| Store | Default path | Env var | Contents |
|---|---|---|---|
| Analyses | `data/silk.db` | `SILK_DB` | `analyses` (json_blob, outcome track record), `market_scores`, `research_missions` (checkpoints) |
| Fact store | `data/silk_store.db` | `SILK_STORE_DB` | `indicators`, `trade_flows`, `collection_runs`, `settings`, `agent_runs` |
| Usage counter | `data/usage.db` | `SILK_USAGE_DB` | `paid_usage(day, calls)` — deliberately isolated |
| Request cache | `data/cache/` | `SILK_CACHE_DIR` | JSON keyed sha1(url+params) |

`SILK_DATA_DIR` routes all four at once (per-store vars win individually);
`/health["storage"]` shows the resolved paths. NEVER mount a volume over `data/`
— the seed CSVs live there. Freshness: `SILK_FRESH_*_DAYS` windows drive
stale-while-revalidate; stale hits serve immediately flagged `status="stale"`
with a `silk-swr` daemon refresh (`SILK_SWR=0` disables).

## 4. The agent roster

- `BaseAgent.run()` guard order (`silk_agents.py:135`): panel-disable
  («معطّل من إعدادات الوكلاء») → PAID guard (outside `/deepen` ⇒ tagged skip,
  zero calls) → steer (explicit arg wins, 500-char clip) → `_execute` with
  automatic exception→failed-report wrapping. Silent failure is impossible.
- `AGENT_CATALOG` (`silk_agents.py:43`) is the ONE catalog — 28 rows after the
  12 missions register additively. `PREF_KEY` sharing: one panel row can govern
  multiple classes (competition → CompetitionAgent + NamedCompetitorsAgent;
  channels → DistributionChannels + Importers; regulatory → Tariffs +
  Requirements).
- Exactly three `PAID = True` agents: LocalPrice, Volza, Explee.
- `LLMMissionAgent` (`silk_llm_runtime.py`) inherits all guards; `silk_gdelt_agent`
  and `silk_openalex_agent` are NOT BaseAgents — keyless tool functions consumed
  by the LLM runtime's `TOOLS` registry.

## 5. Module map (one line each, grouped)

- **Spine**: `silk_engine.py` (analyze pipeline), `api.py` (~1400 lines, all
  routes in `create_app()`), `silk_render.py` (view), `silk_synthesis.py`
  (verdict), `correlation.py` (threads).
- **Data**: `silk_data_layer.py` (v1 primitives), `silk_data_layer_v2.py`
  (derived + store-first), `silk_store.py`, `silk_storage.py`, `silk_cache.py`,
  `silk_usage.py`, `silk_collectors.py` (scheduler + budgets), `silk_seed_data.py`.
- **Agents**: `silk_agents.py` (BaseAgent + core three + jury + catalog) and the
  per-source `silk_*_agent.py` files; `silk_hs_resolver.py`,
  `silk_market_resolver.py` (0.93 threshold), `silk_discovery.py` (reverse
  direction — market → HS opportunities).
- **Deep research**: `silk_missions.py` (12 specs + orchestration),
  `silk_llm_runtime.py` (tool-use loop, TOOLS, citations),
  `silk_llm_provider.py` (raw Messages API, caching, last_error),
  `silk_market_analyst.py` (5 intersections), `silk_ai_judge.py` (deliberately
  unsplit — 16 test files patch `_call`; writer/reviewer/extractors/_isolate),
  `silk_quality_gate.py`, `silk_trace.py`, `silk_evals.py`, `silk_pricing.py`.
- **Old deterministic research**: `silk_research.py` (8 agents),
  `silk_decision.py` (weighted pillars), `silk_trend.py`, `silk_quality.py`,
  `silk_narrative.py` (confidence phrases, badges).
- **Output**: `silk_reports.py` (two docx paths: `_render_research_docx`
  exclusive when `deep_research` present; brief; markdown), `web/index.html`
  (single vanilla-JS file), `tools/gen_*_samples.py`.
- **Ops**: `silk_diagnostics.py` (live probes, `_redact`), `silk_context.py`
  (all the contextvars: deepen, prefs, ai-extras block, data counter).

## 6. Governance docs — reading order for any large change

1. `CLAUDE.md` — conventions + pipeline 1 (does NOT cover `/research`).
2. `docs/ARCHITECTURE.md` — current state; §3 invariant table with guard tests.
3. `docs/EXECUTION_PLAN.md` — settled owner decisions (do not relitigate).
4. `docs/DEEP_RESEARCH_DECISIONS.md` — the incident/decision ledger, waves 1–13.
5. `docs/TUNING.md` — the live debugging/tuning protocol.
6. `docs/AUDIT_STATUS.md` — FROZEN snapshot (2026-07-02); read for method, never edit.

---
name: mission-tuning-and-evals
description: The disciplined procedure for changing any deep-research prompt (missions, analyst, writer/reviewer) in this repo — trace evidence first, single-mission dry runs, then measured eval scoring. Load before editing silk_missions.py instructions, silk_market_analyst.py or silk_ai_judge.py prompts, or before diagnosing a weak /research report.
---

# Mission tuning and evals — evidence before prompt edits

Undisciplined tuning already burned the owner's Claude credits. This skill exists so
that never happens again. Follow it mechanically; do not improvise.

## 0. The iron rule (wave-8 owner decision)

Source: `docs/DEEP_RESEARCH_DECISIONS.md` (section "الموجة ٨", esp. the tuning
decision block near lines 528–539) and `docs/TUNING.md`.

1. **Never edit a prompt because a report looks weak.** First reproduce via trace,
   then classify: structural cause vs prompt cause.
2. Historical proof: both named wave-8 mission failures were **structural bugs, not
   prompt problems** —
   - `pricing_scout` / `opportunity_gaps` dropped real findings (Albert Heijn
     9.96€/kg) because of fenced-JSON parsing (`P0-1`, fixed by
     `_json_candidates()`, `silk_llm_runtime.py:480`).
   - `consumer_culture` / `customs_requirements` gave "no final answer" because
     there was no finalize turn (`P0-2`, fixed by `_FINALIZE_NUDGE`,
     `silk_llm_runtime.py:500`).
   The wave-8 verdict was literally "editing instructions would fix a symptom,
   not a cause" — zero edits to `silk_missions.py` that wave.
3. **But prompt work IS sanctioned** when the trace shows the structural path is
   healthy: tools were called, `tool_call.output` carried real data, parsing
   succeeded (findings > 0), and the mission STILL produced weak/shallow findings.
   The owner reports this is now the common case — under-delivery after the
   structural fixes. In that case proceed to the loop below; do not stall on
   "maybe it's structural" without trace evidence either way.

## 1. The tuning loop (from docs/TUNING.md, expanded)

### Step (a) — single-mission dry run (cheap; never burn all 12 to diagnose 1)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export SEARCH_API_KEY=...      # only pricing_scout/consumer_culture/channels_importers need it
export COMTRADE_API_KEY=...    # optional — raises Comtrade cap from 4 to ~500 calls/day

python3 -c "
from silk_market_resolver import resolve_market
from silk_missions import deep_research
ref, _ = resolve_market('Nigeria')
out = deep_research(ref, product='تمور', hs_code='080410',
                     dry_run=True, only_agent='pricing_scout')
print(out['report'].summary)
"
```

`deep_research()` is defined at `silk_missions.py:396`; `dry_run=True` +
`only_agent=<key>` runs exactly ONE mission and prints every trace event.

### Step (b) — read the trace

Trace file: `data/traces/dryrun-<mission_key>-<ISO3>.jsonl` (naming set at
`silk_missions.py:418-420`; full runs write `run-<ISO3>-<epoch>.jsonl`).

```bash
python3 -c "
import json
for ln in open('data/traces/dryrun-pricing_scout-NGA.jsonl', encoding='utf-8'):
    e = json.loads(ln)
    print(e['kind'], '-', e.get('tool') or e.get('stop_reason') or e.get('summary'))
"
```

Every `tool_call` line carries the real `input`/`output`. The dashboard mirror:
`view["deep_research"]["missions"][key]["trace"]` = `{status, tool_calls, dropped,
gaps}` (built by `silk_render._mission_trace_summary`, `silk_render.py:583`), and
`view["deep_research"]["trace_id"]` names the full JSONL file.

### Step (c) — classify by the symptom table (docs/TUNING.md lines 54–60)

| Symptom in trace | Most likely cause | Fix location |
|---|---|---|
| Every `tool_call.output` empty | Tool failure — key/network, NOT the mission | Check the key/env; tool fns live in `silk_llm_runtime.TOOLS[key]["fn"]` (`silk_llm_runtime.py:289`) |
| Very few `llm_call` events, `finish.summary` says "غير محسوم" | Vague instructions — mission doesn't know when to stop | Sharpen sufficiency criteria in `silk_missions.MISSIONS[key]["instructions"]` |
| `pricing_scout`/`consumer_culture`/`channels_importers` search in English on a non-English market | Market-language suffix lost | Verify `_SEARCH_IN_MARKET_LANGUAGE` (`silk_missions.py:37-39`) is still appended to those three |
| `finish.dropped` consistently high | Claims written without explicit dpN citation | Add to instructions: every number must cite a datapoint id (dpN) |
| `elapsed_ms` high, `tool_calls_used` always hits budget | Budget too tight | Raise via env `SILK_MISSION_TOOL_CALLS` or per-mission `budget={"tool_calls": N}` — do not loosen citation rules |

Structural symptoms (whole reply dropped despite fenced valid JSON; "no final
answer" after budget exhaustion) point at `silk_llm_runtime._json_candidates` /
`_FINALIZE_NUDGE` — those are already fixed; if they recur, that is a code bug,
file it as such, do NOT paper over with prompt text.

### Step (d) — edit ONLY the one mission's instructions

Edit `silk_missions.MISSIONS[<key>]["instructions"]` (the dict spans
`silk_missions.py:50-206`). Do not touch other missions, shared suffixes, or
`allowed_tools` in the same change (see §4).

### Step (e) — re-run that ONE mission

Repeat step (a) for the same `only_agent`. Compare `finish.dropped`, findings
count, and gap notes against the previous trace.

### Step (f) — measure with evals

```bash
python3 -m silk_evals --case <case_key>
```

This re-runs the FULL golden case (12 missions + analyst + synthesis +
writer/reviewer — `silk_evals.run_case`, `silk_evals.py:350`), scores it
(`evaluate_report`, `silk_evals.py:232`), and compares to the last saved score in
`evals/scores.json` (`compare_to_last_score`, `silk_evals.py:334`). A drop of
more than 10 points (`_REGRESSION_DROP_THRESHOLD = 10`, `silk_evals.py:52`) is a
**declared regression — exit code 1** (`silk_evals.py:407-410`). Requires live
network + `ANTHROPIC_API_KEY`; does not run in CI.

### Step (g) — commit the score with the PR

`evals/scores.json` is auto-updated on success (`silk_evals.main`,
`silk_evals.py:404-406`). **Commit it with any prompt-changing PR.** The rule
applies to prompt edits in `silk_missions.py`, `silk_market_analyst.py`, and
`silk_ai_judge.py` (docs/TUNING.md steps ٥–٦).

## 2. The 12 missions inventory

`MISSIONS` dict: `silk_missions.py:50-206`. Run order `MISSION_ORDER`:
`silk_missions.py:209-213`. Missions 1–11 run in parallel
(`ThreadPoolExecutor`, per-task `contextvars.copy_context()` —
`silk_missions.py:345-351`; a single Context cannot be `.run()` from two
threads). `opportunity_gaps` runs LAST, consuming missions 1–11 findings as
citable DataPoints via `extra_findings` (`silk_missions.py:386-392`).
Per-mission timeout: `SILK_MISSION_TIMEOUT_S` default 90 (`silk_missions.py:253`).

Budgets (`silk_missions.py:229-250`): default `tool_calls=5` /
`max_output_tokens=4000` (`SILK_MISSION_TOOL_CALLS` / `SILK_MISSION_MAX_TOKENS`);
the six deep missions get `tool_calls=9` (`SILK_DEEP_MISSION_TOOL_CALLS`,
`_DEEP_RESEARCH_MISSIONS`, `silk_missions.py:241-243`).

| # | key | role (one line) | allowed_tools | budget |
|---|---|---|---|---|
| 1 | `pricing_scout` | Real competitor retail/wholesale prices; price ladder of ≥3 stores; unlinked price = "غير موثَّق" | web_search, trends_interest | 9 |
| 2 | `consumer_culture` | Consumption habits, halal/Muslim share (lookup_reference demographics), seasons, origin sensitivity | web_search, trends_interest, lookup_reference, openalex_search | 9 |
| 3 | `trade_flow` | Import volume + 5-year growth strictly from comtrade_imports | comtrade_imports | 5 |
| 4 | `demographics_economy` | Population/income/Muslim share → computed target-segment size | worldbank_indicator, lookup_reference | 5 |
| 5 | `competitors` | Country-level supplier shares + HHI via comtrade_competitors FIRST, then named companies via web | comtrade_competitors, comtrade_imports, web_search | 9 |
| 6 | `customs_requirements` | Entry checklist from lookup_reference requirements table first; web only to verify updates | lookup_reference, web_search | 5 |
| 7 | `tariffs_agreements` | Applied tariff (wits_tariff) + agreement membership; below-MFN = "تفضيل محتمل — تحقق" | wits_tariff, lookup_reference | 5 |
| 8 | `logistics` | LPI + best-fit port from ports table; unobserved shipping cost = declared gap | worldbank_indicator, lookup_reference, web_search | 5 |
| 9 | `channels_importers` | Entry doors; named candidates tagged "غير موثَّقين — التحقق عبر التعميق" | channels_importers, web_search | 9 |
| 10 | `demand_trends` | FOUR mandated trends_interest calls (5-y, 12-m, "رمضان <المنتج>", brand term) compared explicitly | trends_interest, faostat_supply, openalex_search | 9 |
| 11 | `risk_news` | WGI indicators, FX across ≥3 years computed, GDELT top-10 or web fallback of ≥5 dated headlines | worldbank_indicator, gdelt_news, web_search, openalex_search | 9 |
| 12 | `opportunity_gaps` | Synthesis over missions 1–11 findings; every conclusion cites a dpN or tool result | openalex_search (optional only) | 5 |

Shared instruction suffixes: `_SEARCH_IN_MARKET_LANGUAGE` (`silk_missions.py:37`)
and `_MIN_FOUR_SEARCH_ANGLES` (`silk_missions.py:44`).

Run-wide caps (graceful stop, declared gap): `SILK_RESEARCH_MAX_LLM_CALLS`
default 40 and `SILK_RESEARCH_MAX_TOOL_CALLS` default 100, checked in
`silk_llm_runtime._run_loop` (`silk_llm_runtime.py:711-712`).

## 3. Eval axes (silk_evals.py)

Weights (`AXIS_WEIGHTS`, `silk_evals.py:45-51`):

| axis | weight | how scored |
|---|---|---|
| citation_correctness | 0.35 | programmatic, **binary 0/100** — ONE fabricated number zeroes it (`citation_correctness_score`, `silk_evals.py:188-203`) |
| section_completeness | 0.15 | Claude judge (`_FAST_MODEL`) |
| gaps_declared | 0.15 | Claude judge |
| recommendation_grounded | 0.20 | Claude judge |
| intersections_quality | 0.15 | Claude judge |

Claude axes need a key; without one they return `None` with note
"محاور كلود غير محسوبة — بلا مفتاح ANTHROPIC_API_KEY" and weights renormalize
(`silk_evals.py:253-264`).

`formula_grounded_numbers` (`silk_evals.py:150-185`, the wave-12 debt-1 fix)
accepts derived numbers (TAM/SAM/SOM, segment size, margin) when the equation
checks out arithmetically AND at least one operand traces to a real cited number
(directly or through a prior equation chain). It **rejects assumption-only
chains** — an equation whose both operands are unsourced assumptions is treated
as fabricating a chain from nothing. Explicit assumption markers near an operand
("افتراض", "بافتراض", "نفترض", "assumption") exempt that literal only.

**Golden cases**: `evals/golden_cases.json` is DELIBERATELY `[]`. A real case
requires a manually verified live Comtrade number carrying `source_url` +
`verified_at`/`verified_by` (`validate_case`, `silk_evals.py:281-298`; schema
`evals/golden_cases.schema.json`). Fabricating one violates the founding
principle. The copy-paste runbook for creating the first case is
`docs/DEEP_RESEARCH_DECISIONS.md` → "خطوات أول جلسة حية" → "الخطوة ٣" (pull the
number directly from Comtrade via `silk_data_layer.comtrade_trade`, never from a
Claude output; commit `golden_cases.json` and `scores.json` together).

## 4. What NOT to touch when tuning

1. **`_FINALIZE_NUDGE` single-shot semantics** (`silk_llm_runtime.py:500-508`,
   sent at `:719` and `:749-752`): it fires ONCE — never turn it into a retry
   loop. Failure after the forced turn is a declared gap, not a retry candidate.
2. **dpN citation dropping**: uncited claims are dropped BY DESIGN in
   `_run_loop`. Loosening it (accepting claims without `datapoint_ids`) is
   fabrication. If `finish.dropped` is high, fix the mission's citation
   instruction, never the dropper.
3. **`allowed_tools` lists**: never add a tool name to a mission without the
   corresponding real entry in `silk_llm_runtime.TOOLS`
   (`silk_llm_runtime.py:289` — 11 tools: comtrade_imports,
   comtrade_competitors, worldbank_indicator, wits_tariff, trends_interest,
   faostat_supply, web_search, gdelt_news, openalex_search, channels_importers,
   lookup_reference). A phantom tool name is a silent no-op.
4. **`_SEARCH_IN_MARKET_LANGUAGE` suffix** (`silk_missions.py:37-39`): must stay
   appended to pricing_scout / consumer_culture / channels_importers.

## 5. Known-weak-mission checklist (check tools BEFORE blaming the prompt)

The `competitors` mission historically had **no tool at all** for country-level
supplier breakdown (`comtrade_imports` returns world totals only, `partner=0`) —
that, not its prompt, explained the 0.0 coverage in the Spain run. Wave 10 added
`comtrade_competitors` (+ HHI) and instructions mandating it before any web
search (`docs/DEEP_RESEARCH_DECISIONS.md` §10.2أ, ~lines 706-715; instructions
now at `silk_missions.py:97-110`).

So, for ANY weak mission, in order:
1. Does its `allowed_tools` list actually contain a tool that can supply the
   missing data class? If not, the fix is a new tool in
   `silk_llm_runtime.TOOLS` + adding it to `allowed_tools`, not prompt prose.
2. Did the trace show that tool being called and returning data? If it returned
   nothing → key/network (symptom table row 1).
3. Only if data arrived and the summary is still weak → edit instructions
   (step d), re-run (step e), measure (step f).

## 6. Cost discipline

- One dry run of one mission ≈ its budget: ≤5 or ≤9 tool calls, ≤4000 output
  tokens. A full `/research` run ≈ up to 15 Claude calls. NEVER run the full
  pipeline to diagnose one mission.
- `python3 -m silk_evals --case ...` is a full run — use it to MEASURE after a
  fix, not to explore.
- This dev environment has no key and no network: everything here degrades to
  declared gaps by design. Live tuning happens only on an environment with
  `ANTHROPIC_API_KEY` (see the env block in `docs/DEEP_RESEARCH_DECISIONS.md`
  "المتطلبات البيئية").

---
name: research-report-quality
description: Diagnoses "the report is poor / unconvincing / disconnected numbers" complaints against /research output by locating WHICH pipeline layer is at fault (missions, analyst, writer, reviewer, render sanitization, or quality gate) and fixing it there. Load whenever the owner or a client complains about report quality, empty intersections, missing narrative, leaked plumbing, or a skeleton report.
---

# Research report quality — find the guilty layer, fix it there, iterate for cents

The #1 operator complaint is "the output lacks intelligence." Report quality failures
are almost never one bug — they are one LAYER failing while the others work. Never
"improve the prompt" before you know which layer dropped the ball. A full /research
run costs ~$2; this skill's iteration loop costs cents.

## 1. The layer map (order = data flow; later layers consume earlier output)

| # | Layer | Code | What it decides |
|---|-------|------|-----------------|
| 1 | 12 missions gather findings | `silk_missions.py:50` (`MISSIONS`), run order `MISSION_ORDER` at `silk_missions.py:209`, executed by `run_all_missions()` at `silk_missions.py:302` via the tool-use loop `silk_llm_runtime.run_llm_agent()` (`silk_llm_runtime.py:800`) | WHAT evidence exists. Each mission = key + `instructions` + `allowed_tools` (from `silk_llm_runtime.TOOLS`, `silk_llm_runtime.py:289`). Uncited claims are dropped, never kept (`_parse_output`, `silk_llm_runtime.py:527`). |
| 2 | Analyst builds exactly 5 intersections | `silk_market_analyst.py` — `REQUIRED_CATEGORIES` at lines 30-31: `demand, entry_cost, price_competitiveness, entry_door, swot`; category matching at lines 133-140 | The analytical spine. Matching is NORMALIZED (lowercase + strip) since the wave-9 live bug: Claude returning `"Demand"` instead of `"demand"` silently emptied all 5 intersections (comment at `silk_market_analyst.py:128-132`). Timeout is `_LONG_TIMEOUT` (`SILK_AI_LONG_TIMEOUT_S`, default 300s — `silk_ai_judge.py:25`). |
| 3 | Writer produces the 11-section report | `silk_ai_judge.deep_report()` at `silk_ai_judge.py:640`; `_REPORT_SECTIONS` at `silk_ai_judge.py:574-586`; `_MISSION_TO_SECTION` at `silk_ai_judge.py:589-601` | HOW it reads. The prompt (lines 667-764) bans raw confidence numbers in prose, bans "لا تتوفر بيانات كافية" when ≥2 combinable facts exist, requires explicit TAM/SAM/SOM equations, Markdown tables for price ladders/requirements, the "### خارطة طريق الدخول (٩٠ يوماً)" roadmap, and a bold "**ماذا يعني هذا لقرارك:**" closer per section. |
| 4 | Reviewer loop | `review_report()` at `silk_ai_judge.py:788` (Haiku via `_FAST_MODEL`, 30s timeout) inside `write_reviewed_report()` at `silk_ai_judge.py:832` — max 2 cycles (`max_cycles=2`) | Checks every number against raw facts + argument structure. Deterministic section-order check `_section_order_issues()` at `silk_ai_judge.py:771` runs regardless of Claude. Unresolved notes surface in `view["deep_research"]["limits"]`. |
| 5 | Render sanitization | `silk_render._strip_internal_plumbing()` at `silk_render.py:569`; `_strip_raw_json_leak()` at `silk_render.py:535`; applied to report text at `silk_render.py:682` and mission summaries at `silk_render.py:631` | Strips `LLMAgent:x` / `LLMMissionAgent:x` (replaced by Arabic mission name), `dp7`/`[dp7]` tags, and whole-JSON summaries before anything reaches a client. |
| 6 | Quality gate | `silk_quality_gate.run_quality_gate()` at `silk_quality_gate.py:229` — 10 deterministic check functions, zero Claude, zero network | Never blocks delivery — verdict `PASS` / `PASS-WITH-WARNINGS` / `FAIL` attached via `_attach_quality_gate()` (`api.py:759`). Non-repairable findings become `methodology_notes` injected into the docx under "حدود المنهجية وجودة البيانات" inside section 2 (`silk_reports.py:1058-1068`). |

Downstream consumers: `view["deep_research"]` is built by `silk_render._deep_research_view()`
(`silk_render.py:613`); docx by `silk_reports.render_docx()` (`silk_reports.py:1215`).

## 2. Symptom → layer decision table

Work top-down: reproduce the symptom in `view["deep_research"]`, then jump to the row.

| Symptom (as the owner phrases it) | Guilty layer | Verify | Fix at |
|---|---|---|---|
| All 5 intersections say "دليل غير كافٍ" but the same report shows real evidence (prices, Muslim-population numbers, EU requirements) | Analyst category matching OR analyst/writer timeout | Check `view.deep_research.analyst.missing_categories` and `report.failure_reason`. If report text is also empty → timeout (PR #69 history: analyst+writer hit a fixed 60s and the UI falsely said "يتطلب مفتاح كلود"; `failure_reason()` at `silk_ai_judge.py:68` now distinguishes). Read trace `report_call` events. | Matching: `silk_market_analyst.py:133-140`. Timeout: `SILK_AI_LONG_TIMEOUT_S`. Gate check: `_check_intersection_insufficiency` (`silk_quality_gate.py:118`) and `_check_analyst_layer_failure` (`silk_quality_gate.py:189`) already flag both. |
| "Numbers feel disconnected / no narrative / data dump" | Writer prompt — or a computed-but-unwired output | First confirm the value is actually in the view. PR #66 precedent: `silk_engine` computed `result["report"]` (`silk_engine.py:259-265`) but the view never exposed it until `"ai_report": result.get("report")` was added at `silk_render.py:818`. Computed-but-unwired is its own failure class — grep the view before touching prompts. | If wired: the narrative rules live ONLY in the `deep_report` prompt (`silk_ai_judge.py:667-764`, esp. lines 676-681 "تقرير تحليلي مهني لا تفريغ بيانات خام"). Extend there; then run the cheap loop (§3). |
| Raw JSON, `LLMAgent:x`, or `dp7` tags visible in the report | Render sanitization regression + quality gate regression | `_INTERNAL_PLUMBING_RE` (`silk_quality_gate.py:37`) should have flagged it; `_strip_internal_plumbing` (`silk_render.py:569`) should have stripped it. A leak means a NEW text path bypasses `silk_render` — find where that string reaches the view without passing line 631/682. | Route the new field through `_strip_internal_plumbing`; add a regression test next to `tests/test_wave_p2_writer_trace_regen_sanitize.py` / `test_wave_p3_writer_diagnostics_and_json_leak.py`. |
| Report is a skeleton, note says "يتطلب مفتاح كلود" | Wrong endpoint or bypassed readiness gate | Incident PR #58 (full post-mortem: `docs/DEEP_RESEARCH_DECISIONS.md:266-360`): the "bad deep report" was actually a `/analyze` result — the dashboard had no path to `POST /research` at all. Check which endpoint produced it (`result` has `deep_research` key only for /research). Also check whether the caller passed `allow_degraded=true` to bypass the 409 from `_research_readiness()` (`api.py:504`, enforced at `api.py:996-1001`). | Not a report bug. Use `POST /research`; do not pass `allow_degraded` unless a skeleton is explicitly wanted; `view["deep_research"]["degraded"]`/`degraded_reason` carry the banner. |
| Trace shows a finding was gathered, but it's missing from the report | Fenced-JSON parse OR uncited-claim dropping | Open the trace (§3 step 4). `finish.dropped` lists every claim dropped for "no valid cited datapoint_id" (`silk_llm_runtime.py:571-575`); mission summary appends "أُسقطت N بند(ود) بلا استشهاد" (`silk_llm_runtime.py:850-852`). Fenced ```json``` replies used to be lost entirely (wave-8 P0-1) — `_json_candidates()` at `silk_llm_runtime.py:480` now tries each fence first. | High `dropped` → sharpen the mission's citation instruction in `MISSIONS[key]["instructions"]`. Parse failure ("رد كلود غير قابل للتفسير كـ JSON" gap) → `_json_candidates`/`_parse_output`. |
| Sections out of order / a section deleted | Writer ignored the mandatory structure | `_section_order_issues()` (`silk_ai_judge.py:771`) — deterministic; the gate's `_check_section_structure` (`silk_quality_gate.py:140`) turns it into verdict FAIL. The reviewer feeds these back for the revision cycle. | Section list is `_REPORT_SECTIONS` (`silk_ai_judge.py:574`) — order is mandatory ("الترتيب هنا **إلزامي**"); never reorder it, fix the writer prompt or revision loop. |
| A mission section is empty/generic ("competitors 0.0 coverage") | Mission instructions or a failing tool | Trace `tool_call` events: empty `output` on every call = tool/key problem, not prompt (`docs/TUNING.md` symptom table). Precedent: competitors mission now forces `comtrade_competitors` before any web search (`silk_missions.py:98-110`). | `MISSIONS[key]["instructions"]` + budget `_budget_for()` (`silk_missions.py:246`; deep set gets 9 tool calls via `SILK_DEEP_MISSION_TOOL_CALLS`). Mission timeout: `SILK_MISSION_TIMEOUT_S` default 90s (`silk_missions.py:253`). |

## 3. The cheap iteration loop — NEVER re-run 12 missions to test a writer change

`POST /analyses/{id}/report` (`api.py:1296`, `regenerate_report`) rebuilds the report
from saved mission checkpoints (`silk_storage.load_mission_checkpoints`, `silk_storage.py:253`)
for the cost of ONE writer call (+ reviewer). The endpoint docstring says it explicitly:
"§سنتات لا دولارات" — cents, not dollars.

1. Find a persisted /research analysis id:
   `curl -s -H "X-API-Key: $SILK_API_KEY" localhost:8000/analyses` (handler `api.py:1209`)
   — pick one whose record has a `deep_research` section.
2. Make your writer/reviewer/prompt change (`silk_ai_judge.py`).
3. Regenerate: `curl -s -X POST -H "X-API-Key: $SILK_API_KEY" localhost:8000/analyses/<id>/report`
   - 400 = not a /research run; 409 = no mission checkpoints stored (older run — you must
     do one full run first); `{"report": null, "note": ...}` = AI extras blocked
     (`_free_ai_extras_allowed`, called at `api.py:1323`).
4. Inspect, in this order:
   - `view.deep_research.report.text` (present? narrative? sections in order?)
   - `view.deep_research.quality_gate.verdict` + `.findings` (re-attached at `api.py:1344`)
   - trace `report_call` events: `python3 -c "import json;[print(json.loads(l).get('stage'), json.loads(l).get('elapsed_ms'), json.loads(l).get('error_type')) for l in open('data/traces/<trace_id>.jsonl',encoding='utf-8') if '\"report_call\"' in l]"` —
     stages are `draft` / `revision` / `review`; on failure the event carries `error_type`,
     `error_message`, `status_code` (`silk_ai_judge.py:625-636`).
5. For MISSION changes (layer 1) use the single-mission dry run instead — one mission,
   full trace to terminal, no 12-mission burn (`docs/TUNING.md`):
   `deep_research(ref, product='تمور', hs_code='080410', dry_run=True, only_agent='pricing_scout')`
   (`silk_missions.py:396`, dry-run branch at 423-441).
6. Only after the cheap loop passes, measure a FULL run against the golden case:
   `python3 -m silk_evals --case nigeria_tea` — score drop > 10 vs `evals/scores.json`
   exits 1 (declared regression). Commit `evals/scores.json` with any prompt-touching PR.

## 4. Judging quality like the departing engineer

Run this checklist on any report before calling it "fixed":

1. Open the committed expectations: `samples/report_full_latest.docx`,
   `samples/research_report_latest.docx` (and `samples/report_full_latest.md`).
   Rule §10.6: every render-layer change regenerates these samples in the same PR.
2. Run the gate manually on the stored view:
   ```bash
   python3 -c "
   import json, silk_storage, silk_quality_gate
   found = silk_storage.get_analysis(<id>)
   out = silk_quality_gate.run_quality_gate(found['view'])
   print(out['verdict']); [print('-', f['check'], f['note']) for f in out['findings']]"
   ```
   FAIL is triggered only by `section_structure`, `agent_failed`, or
   `analyst_layer_failed` (`silk_quality_gate.py:264-266`).
3. Every number must have a source line — structural via `components_detail`
   (`silk_render.py:732-739`); in deep-research prose, sources are in-sentence
   parentheses and full confidences live in the auto-built technical appendix,
   never raw "(ثقة 0.6)" in prose (banned at `silk_ai_judge.py:750-756`, gate
   regex `_RAW_CONFIDENCE_RE` at `silk_quality_gate.py:31`).
4. The 5 intersections are populated: `view.deep_research.analyst.by_category`
   has ≥1 badged entry per category, `missing_categories` is empty. Any category
   with ≥2 items must NOT read "دليل غير كافٍ" (gate check at `silk_quality_gate.py:118`).
5. Section order/completeness: `from silk_ai_judge import _section_order_issues;
   print(_section_order_issues(text))` — must return `[]`.
6. Executive summary states a THESIS ("التوصية X لأن ...؛ وتتحول إلى GO إذا ..."),
   each main section ends with "**ماذا يعني هذا لقرارك:**", the 90-day roadmap
   subheading "### خارطة طريق الدخول (٩٠ يوماً)" exists under section 10.

## 5. Verification

```bash
python3 -m pytest tests/test_wave9_sellable_report.py tests/test_wave10_quality_and_structure.py tests/test_p2_report_structure.py -q
```
All three files exist in `tests/`. For sanitization/regen changes also run
`tests/test_wave_p2_writer_trace_regen_sanitize.py` and
`tests/test_wave_p3_writer_diagnostics_and_json_leak.py`; for mission-layer changes
`tests/test_wave6_missions.py`, `tests/test_wave6_llm_runtime.py`,
`tests/test_wave8_live_tuning.py`. Then the full hermetic suite:
`python3 -m pytest tests/ -q` (CI runs exactly this).

Hard rules that survive any fix: verdicts come only from `silk_synthesize` — the writer
explains the ready verdict, never issues its own (`silk_ai_judge.py:659`); no fabricated
numbers — a gap is declared, never filled; extend `build_view`, never add a parallel
render path.

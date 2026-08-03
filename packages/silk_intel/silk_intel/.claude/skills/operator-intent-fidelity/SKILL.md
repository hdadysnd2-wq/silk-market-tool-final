---
name: operator-intent-fidelity
description: Maps every channel through which operator intent enters the system (agent commands, mission instructions, product_card, request fields, writer prompt), where each gets structurally diluted or dropped, and how to fix "I wrote exactly what I need and it didn't execute it" complaints. Load when the owner says the system ignores, weakens, or misexecutes his written instructions.
---

# Operator intent fidelity — where written intent enters, where it dies

The owner's #1 complaint: "even when I write exactly what I need, the system doesn't
execute it accurately." That is usually not disobedience — it is a channel mismatch:
the intent was typed into a channel that is DESIGNED to have limited authority, or a
channel that structurally drops it. Diagnose the channel first, then move the intent
to the right lever.

## 1. The intent channels inventory (strongest to weakest authority)

| Channel | Where it enters | Authority level | Anchors |
|---|---|---|---|
| (b) Mission instructions | `silk_missions.MISSIONS[key]["instructions"]` (`silk_missions.py:50-206`) | STRONGEST for /research data-gathering. Goes into the Claude SYSTEM prompt un-isolated: `system = f"{_PRINCIPLE}\n\n{mission.get('instructions', '')}"` (`silk_llm_runtime.py:641`). This is where "search in the market's language", "call comtrade_competitors FIRST", "≥4 search angles" live. | `silk_missions.py:50`, `silk_llm_runtime.py:641` |
| (e) Writer prompt | `silk_ai_judge.deep_report()` (`silk_ai_judge.py:640`, prompt body 667-764) | The ONLY place report structure/tone/format is decided (sections, TAM/SAM/SOM equations, tables, "**ماذا يعني هذا لقرارك:**" closers). Report-reading complaints belong here, nowhere else. | `silk_ai_judge.py:640` |
| (c) product_card + own_price | API models: `AnalyzeRequest.product_card` (`api.py:212`), `own_price` (`api.py:235`); /research merge at `api.py:1021-1027` (own_price is folded INTO product_card) | Narrative context per mission (`extra_context`) + explicit margin math in the analyst. Wave-9 live bug: it was accepted by the API model but reached NO consumer — "الموقع التنافسي" was absent from every deep report (documented in the `analyze_market` docstring, `silk_market_analyst.py:103-106`). Current wiring: `api.py:801` → `run_all_missions` (`silk_missions.py:327-333`) via `_product_card_context()` (`silk_missions.py:263`), and `api.py:817` → `analyze_market` (`silk_market_analyst.py:117-120`). | `api.py:1021-1027`, `silk_missions.py:263` |
| (d) Request fields product / market / hs_code | User message of every mission call, each `_isolate()`-wrapped (`silk_llm_runtime.py:665-669`); writer isolates them too (`silk_ai_judge.py:658`) | Scope selection only. Treated as untrusted data — a "product name" containing instructions will not steer anything (by design, prompt-injection guard). | `silk_llm_runtime.py:665-669` |
| (a) Agent commands (settings panel «إعدادات الوكلاء») | `agent_prefs[key]["cmd"]` → `silk_context.agent_command()` clips to 500 chars (`silk_context.py:76-78`) → `BaseAgent.run` puts it in `task["instruction"]` (`silk_agents.py:164-168`) → appended to mission instructions inside `_isolate()` (`silk_llm_runtime.py:824-828`) or wrapped by `silk_ai_judge._user_steer()` (`silk_ai_judge.py:210-223`) | WEAKEST by design. The preamble literally says: "توجيه المستخدم (وجّه التركيز فقط — لا تخترع بيانات ولا أرقاماً): " (`silk_ai_judge.py:222-223`; runtime variant "توجيه المستخدم (وجّه التركيز فقط — لا تخترع بيانات): " at `silk_llm_runtime.py:827`). Steer text is deliberately DATA with limited authority: presentation/focus only; a data agent's numbers are never altered (CompetitionAgent top-N is row-count only). | `silk_context.py:76-78`, `silk_ai_judge.py:210-223` |

## 2. WHY intent gets lost — the structural dilutions (all deliberate or historical)

| Operator writes X | System does Y | Because Z | Fix at W |
|---|---|---|---|
| A 900-char detailed command in the agent panel | Only the first 500 chars arrive, silently | `agent_command()` clips: `[:500]` (`silk_context.py:78`); `BaseAgent.run` clips again (`silk_agents.py:164-165`); `_user_steer` clips `extra` (`silk_ai_judge.py:219`) | Move the substance into `MISSIONS[key]["instructions"]` (no clip, system-level); keep panel commands short focus nudges |
| "Report the price as $X" in a steer command | Number never appears (or appears as declared gap) | Steer is wrapped in `_isolate()` + "لا تخترع بيانات ولا أرقاماً" preamble — Claude is TOLD it is untrusted data that cannot create numbers | Working as designed — see §4. If the number is real operator data, it belongs in `product_card` (a citable fact channel), not a steer |
| A command for an agent whose panel row is off | Agent returns a tagged skipped report, command never runs | Disabled guard fires BEFORE steer handling: "معطّل من إعدادات الوكلاء — disabled by user setting (skipped, no call attempted)" (`silk_agents.py:150-156`) | Re-enable the row (`GET/POST /settings/agents`); check `silk_store.load_agent_settings` for a stale saved "off" |
| Prefs sent with /analyze, then /deepen expected to honor them | /deepen ignores the panel entirely | `/deepen` (`api.py:681-694`) opens `deepen_context()` but no `agent_prefs_context` — an explicit paid request wins over the panel (settled design, CLAUDE.md) | Nothing to fix; set expectations. Panel governs /analyze (inherit at `api.py:556-558`) and /research (inherit stored/saved at `api.py:1014-1016`) |
| Prefs set, but parallel missions ignore them | Threads silently saw default contextvars (steer ignored, blocks not applied) — historical failure class | `ThreadPoolExecutor` does not inherit contextvars; fixed with per-task `contextvars.copy_context().run` (`silk_missions.py:345-351`, comment 335-344 documents the silent failure) | Any NEW thread/pool you add must copy context the same way — this is the first thing to check when intent works sync but not in /research |
| product_card filled in the request, report shows no competitive position | Historical: accepted by pydantic, consumed by nothing (wave-9) | Computed-but-unwired is a recurring failure class here (same as the PR #66 ai_report) | Verify the full chain: `api.py:1021-1027` → `silk_missions.py:327` (`card_ctx`) → `silk_market_analyst.py:117-120`. If you add a new intent field to a request model, grep for its consumer the same day |
| Steer arrives but output barely changes | Steer only ever reaches Claude agents' prompts; deterministic agents ignore `task["instruction"]` numerically | "Commands steer presentation/focus ONLY" — enforced in `BaseAgent.run` docstring contract (`silk_agents.py:135-145`) | If the intent is about WHAT data, it is a mission-instruction or tool change, not a steer (§3) |

## 3. Decision procedure for a new intent requirement

Run top-down; stop at the first match:

1. **Is it about WHAT data to gather / how hard to look?**
   → Edit `silk_missions.MISSIONS[key]["instructions"]` (`silk_missions.py:50-206`).
   Follow the eval protocol in `docs/TUNING.md`: single-mission dry run
   (`deep_research(..., dry_run=True, only_agent=key)`), read the trace, then
   `python3 -m silk_evals --case nigeria_tea` and commit `evals/scores.json`.
   Budget too tight for the new demand? `_budget_for()` / `SILK_DEEP_MISSION_TOOL_CALLS`
   (`silk_missions.py:229-250`).
2. **Is it about HOW the report reads (structure, tone, tables, emphasis)?**
   → The `deep_report` writer prompt (`silk_ai_judge.py:667-764`) — the only
   structure/tone lever. Test via `POST /analyses/{id}/report` (cents, not a $2 rerun).
3. **Is it about WHICH agents run, or a per-run focus nudge?**
   → Settings panel / `agent_prefs` (`api.py:556-558`, catalog `silk_agents.AGENT_CATALOG`).
4. **Does it need data the current tools cannot fetch?**
   → It is a NEW TOOL in `silk_llm_runtime.TOOLS` (`silk_llm_runtime.py:289`) plus an
   `allowed_tools` entry — not a prompt edit. No prompt can make Claude cite a
   datapoint id that no tool registered; the uncited claim would be dropped
   (`silk_llm_runtime.py:571-575`).

Wave-8 owner decision (docs/DEEP_RESEARCH_DECISIONS.md §الموجة ٨): structural fixes
before prompt edits — every wave-8 root cause turned out to be parsing/wiring/structure
(`_json_candidates`, `_FINALIZE_NUDGE`, inverted docx), not prompt weakness. HOWEVER:
the owner now reports prompts still under-deliver even when traces show structure is
sound — so prompt-level work IS sanctioned, on one condition: bring trace evidence
first (`finish.dropped` low, `tool_call.output` non-empty, `report_call` succeeded)
proving the failure is in wording, then edit the prompt and measure with `silk_evals`.

## 4. The tension you must preserve: intent NEVER overrides no-fabrication

CLAUDE.md, the founding principle (enforced, not advisory):

> **The system never fabricates data.** Every value travels as a
> `DataPoint(value, source, confidence, note, retrieved_at)` (`silk_data_layer.py`).
> On any failure — no key, no network, bad payload — the value is `None` with
> `confidence=0.0` and a `note` explaining why. Numbers are never guessed, gaps are
> declared, and tests enforce this hermetically.

A steer command asking for numbers the data does not support must produce a DECLARED
GAP, not compliance. This is why the steer preamble says "لا تخترع بيانات ولا أرقاماً",
why steer text passes through `_isolate()` like any external text, and why the
citation registry drops uncited claims. When "improving intent-following", never:
- move steer text out of `_isolate()` or strip the focus-only preamble,
- give the panel a channel to inject facts (settings persist outside the env-key
  allowlist precisely so no key/fact can be smuggled — `silk_store.save/load_agent_settings`),
- let a prompt edit permit an unregistered number. Fidelity means executing the
  operator's ANALYTICAL intent accurately, with real data or an honest "غير مرصود".

## 5. Worked example — one steer command end-to-end

Operator saves for `pricing_scout`: «ركّز على أسعار الجملة لا التجزئة، وقارن بالسوق السعودي».

1. UI posts `agent_prefs = {"pricing_scout": {"on": true, "cmd": "ركّز على أسعار الجملة..."}}`
   to `/analyze` or `/research`; body normalized by `_clean_agent_prefs` (`api.py:575` —
   on/cmd only, nothing else survives). A request WITHOUT `agent_prefs` inherits the
   saved panel settings (`api.py:556-558`; /research: `api.py:1014-1016`).
2. The handler enters `silk_context.agent_prefs_context(prefs)` (`api.py:561` / `api.py:789`).
3. /research fans out missions; each thread gets a contextvars snapshot via
   `contextvars.copy_context().run` (`silk_missions.py:350`) — without this the steer
   would silently vanish in parallel threads.
4. `LLMMissionAgent.run(task)` → `BaseAgent.run` (`silk_agents.py:135`): row enabled?
   (else «معطّل من إعدادات الوكلاء» skip, zero calls). Then
   `steer = instruction or silk_context.agent_command("pricing_scout")` — explicit
   `instruction` arg wins over the saved command — clipped to 500 chars and set as
   `task["instruction"]` (`silk_agents.py:164-168`).
5. `run_llm_agent` appends it to the mission's instructions, isolated:
   `"توجيه المستخدم (وجّه التركيز فقط — لا تخترع بيانات): " + _isolate(instruction)`
   (`silk_llm_runtime.py:824-828`). So Claude sees the wholesale-focus request inside
   `[RAW_FINDINGS_START]...[RAW_FINDINGS_END]` delimiters, subordinate to the mission
   system prompt.
6. Effect: Claude biases its `web_search` queries toward wholesale prices. It still
   cannot invent a Saudi comparison price — if no tool returns one, the comparison
   appears in `gaps`, and the steer is declared in the report summary
   (`silk_agents.py:141-144` contract). Claude one-shot judges get the same command
   via `silk_ai_judge._user_steer(key, extra)` inside their `_isolate` block
   (`silk_ai_judge.py:210-223`).
7. Verify fidelity in the trace: `data/traces/<trace_id>.jsonl` `llm_call` events show
   the steer inside the prompt; `tool_call.input` shows the wholesale-flavored queries.

## 6. Verification

```bash
python3 -m pytest tests/test_agent_settings_panel.py tests/test_p3_prefs_and_chat.py tests/test_wave7_agent_panel_fallback.py tests/test_wave6_missions.py -q
```
Then the full hermetic suite `python3 -m pytest tests/ -q`. Any change to an intent
channel ships a hermetic test the same day (BaseAgent house rule), and any prompt
change commits an updated `evals/scores.json`.

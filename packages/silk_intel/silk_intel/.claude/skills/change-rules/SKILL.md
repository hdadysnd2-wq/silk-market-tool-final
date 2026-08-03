---
name: change-rules
description: The immutable invariants, the settled owner decisions that must not be relitigated, and safe-change checklists per change type for this repo. Load before designing or reviewing ANY change — it defines what must never be touched and what every change must carry.
---

# Change rules — invariants, settled decisions, safe-change checklists

## A. Immutable invariants (each is enforced structurally and guard-tested)

1. **No fabrication — the founding principle.** Every value travels as
   `DataPoint(value, source, confidence, note, retrieved_at, status)`
   (`silk_data_layer.py:111`). Failure = `value=None, confidence=0.0` + Arabic
   note explaining why. Malformed records are DROPPED, never zeroed
   (`primary_value`, `silk_data_layer.py`); a Saudi-absent share of 0.0 is an
   INFERRED zero capped at confidence 0.6, never an observed one. Any new data
   path follows this contract or review rejects it.
2. **`silk_synthesis.synthesize()` is the ONLY verdict entry point**
   (`silk_synthesis.py:90`). The old `ai_verdict` duality was deliberately
   deleted. `silk_decision`'s weighted verdict enters only via `build_view`
   precedence (a valid `row["decision"]` replaces the jury line in the VIEW —
   it is not a second synthesis path). Stage-1 deterministic jury can never be
   disabled; the panel's `synthesis` row only kills stage 2.
3. **`silk_render.build_view()` is the ONLY view-model** (`silk_render.py:695`).
   Every surface (dashboard, terminal, docx, brief, markdown, chat context)
   derives from it. Never add a parallel render path; never compute a number in
   a consumer. Provenance (`components_detail`) is built inside the template so
   an unsourced number is structurally impossible.
4. **The paid boundary is structural.** Exactly three PAID agents — LocalPrice
   (`silk_localprice_agent.py:299`), Volza (`silk_volza_agent.py:128`), Explee
   (`silk_explee_agent.py:156`) — cannot execute outside
   `silk_context.deepen_context()` (set only by `POST /deepen`). `POST /analyze`'s
   pydantic model has no paid fields, so they are dropped from any body. Do not
   add a paid field to a free model, ever.
5. **Every external string passes `silk_ai_judge._isolate()`** before reaching
   Claude — including tool outputs' `value` and `source` (the wave-12 audit found
   only `note` was isolated; that hole is closed — don't reopen it), user steer
   commands, market/product names, even `hs_code` from request bodies.
6. **Enrichment never changes `total_score`.** Wrapper exceptions become
   `_enrich_error_dp()` DataPoints (`silk_engine.py:307`); a silent `[]`/`None`
   from a wrapper is a regression by definition.
7. **Money guards fail closed.** `silk_usage.try_reserve_paid_calls`
   (`silk_usage.py:118`): atomic `BEGIN IMMEDIATE`, any DB error refuses.
   Reservations are never refunded — keep it that way (conservative by design).
8. **Store-served values keep their ORIGINAL `retrieved_at`** and carry
   «من المخزن» + the fetch date in the note. Restamping store data as fresh is
   presenting stale as live — an honesty violation, not a cosmetic issue.
9. **`correlation.py` makes zero external calls** — an AST test asserts it
   imports no network library (`tests/test_wave4_correlation.py`). Its threads
   build strictly from in-memory agent findings; incomplete threads are declared
   («سعر غير مرصود»), never invented.
10. **Never delete or modify existing rows in `data/silk.db`.** Schema changes
    are additive: `ALTER TABLE ADD COLUMN` inside `silk_storage.init_db()`, or a
    new `migrations/NNN_*.sql` for the unified store. The `analyses` outcome
    columns are the cumulative track record — sacred.
11. **Arabic user-facing contract strings are tested by exact match**
    («سعر غير مرصود», «من المخزن», «معطّل من إعدادات الوكلاء», …). Changing one
    is an API break: update the tests deliberately and say so in the PR.
12. **Uncited LLM claims are dropped** (`silk_llm_runtime._parse_output`) —
    loosening the dpN citation rule to "improve" coverage is fabrication.

## B. Settled owner decisions — do NOT relitigate (dated 2026-07-02 unless noted)

| Decision | Source |
|---|---|
| SQLite stays; Postgres migration deferred until real multi-user need | `docs/EXECUTION_PLAN.md` القرارات |
| No Redis/RQ/background queues — EVER for this internal tool; threads suffice | `docs/EXECUTION_PLAN.md` |
| Single Anthropic provider; declared stop at cap; NO automatic fallback provider | `docs/VISION.md` §9.5 |
| Wave-3 agents = the selective four; the other six vision agents deferred | `docs/EXECUTION_PLAN.md` |
| Trade-finance layer deferred; nothing implemented | `docs/EXECUTION_PLAN.md` |
| `evals/golden_cases.json` stays `[]` until a manually-verified live Comtrade number exists (source_url + verified_at/by); fabricating one violates the founding principle | `docs/DEEP_RESEARCH_DECISIONS.md`, restated waves 5/9/12 |
| `silk_ai_judge.py` stays unsplit — 16 test files patch `silk_ai_judge._call`; a split silently breaks hermetic patching | `docs/ARCHITECTURE.md` §7.5 |
| `correlation.py` NOT extended to the mission-report shape; old-path threads reach the analyst as non-citable `extra_context` | `docs/DEEP_RESEARCH_DECISIONS.md` Decision 3 |
| Market-match threshold 0.93, not lower — Nigeria/Niger ambiguity deserves a user question, not a guess | `docs/DEEP_RESEARCH_DECISIONS.md` Decision 2 |
| stdlib-first: no PyYAML (hand parser for `config/branding.yaml`), no Anthropic SDK (raw Messages API), no frameworks, vanilla-JS single-file UI (ponytail: YAGNI, minimal) | `.claude/settings.json`, CLAUDE.md Misc |
| Refresh scheduler stays in-process — a Railway volume mounts to exactly one service | `silk_collectors.py` comment, CLAUDE.md |

## C. Safe-change checklists

### Adding a data source / agent
1. Subclass `BaseAgent` (`silk_agents.py`); set `PAID` (almost certainly False),
   `SOURCE`, `PREF_KEY` (check the sharing map — one panel row can govern several
   classes: competition, channels, regulatory all shared).
2. Implement `_execute(task) -> AgentReport`; every failure path returns
   DataPoints per invariant A1 — the base class wraps unexpected exceptions, but
   your expected failures (no key, empty payload) must be declared notes.
3. Add/verify the `AGENT_CATALOG` row (`silk_agents.py:43`) — additive only.
4. Ship the hermetic test THE SAME DAY: offline ⇒ `value is None and
   confidence == 0.0` + note, never zeros.
5. Lazy-import any network/optional lib so the module imports offline and keyless.

### Adding an enrichment layer
1. New `with_*` flag in `analyze()` defaulting False; wrapper catches exceptions
   into `_enrich_error_dp` (`silk_engine.py:307`).
2. Never touch `total_score`. Write your row key once; if correlation should see
   it, extend `correlation.py`'s key reads deliberately.
3. Extend `build_view` (never a new render path); regenerate `samples/`.

### Adding an API endpoint
1. `_require_key` (`api.py:367`) + `_rate_limit` (`api.py:393`) unless it is
   deliberately public reference data (document why).
2. Decide paid gating: does it reach Claude or a paid provider? Then it goes
   through `_guard_paid` (`api.py:427`) or `_free_ai_extras_allowed` (`api.py:481`).
3. TestClient test patches `requests` (NOT socket blocking — it breaks the
   TestClient transport). Auth, rate-limit, and degraded behavior each asserted.

### Touching any prompt (missions / analyst / writer)
Follow `.claude/skills/mission-tuning-and-evals/SKILL.md`: trace evidence first,
single-mission dry run, `python3 -m silk_evals --case <key>`, >10-point drop is a
declared regression, commit `evals/scores.json` with the PR.

### Render/report change
Extend `build_view` → render in each consumer → regenerate committed `samples/`
(rule §10.6, `tools/gen_analyze_samples.py` + `tools/gen_research_sample.py`) →
run the report-structure test files.

### Schema change
Additive only (`ALTER TABLE` in `init_db()` or new `migrations/NNN_*.sql` tracked
in `schema_migrations`). Existing rows untouched. Never a destructive migration.

### Anything touching money
Re-read invariant A7 and `.claude/skills/credit-economics/SKILL.md`. Reservation
before run; failure consumes the reservation; fail closed.

## D. Before you push — every PR

1. `python3 -m pytest tests/ -q` green (~5s; CI runs exactly this).
2. New behavior has new hermetic tests in the same PR.
3. Render touched ⇒ `samples/` regenerated and committed.
4. PR description anchors every claim to `file:line`; absences stated as
   "not found" explicitly (the AUDIT_STATUS method).
5. One wave per PR, branched from fresh `main`, squash-merge `Title (#N)` style.
6. Incidents/decisions recorded in `docs/DEEP_RESEARCH_DECISIONS.md`; label every
   diagnosis with its evidence class (direct reproduction / static code review /
   pending — no evidence).

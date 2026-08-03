---
name: failure-stories
description: The distilled incident ledger of this repo — thirteen real production failures, each with root cause, fix, the rule it produced, and its guard test. Load before shipping any non-trivial change, when a symptom feels familiar, or when tempted to guess a fix without evidence.
---

# Failure stories — mistakes that cost real time and money

Each story: WHAT HAPPENED / ROOT CAUSE / FIX / **THE RULE** / GUARD.
Full forensics live in `docs/DEEP_RESEARCH_DECISIONS.md` (the wave-by-wave ledger).

## 1. The skeleton report delivered as the product (PR #58)
Owner received a docx whose body said "requires Claude key" — as the final deliverable.
**Root cause:** the dashboard had NO path to `/research` at all; its only button called
`POST /analyze`. A correctly-degrading /analyze report was mistaken for a broken
deep-research report. **Fix:** `_research_readiness()` 409 preflight (`api.py:504`),
a real deep-research button, `allow_degraded` stamps a visible DEGRADED banner.
**THE RULE:** before diagnosing output quality, confirm WHICH endpoint produced the
output (`result` has a `deep_research` key only for /research).
**Guard:** `tests/test_wave7_live_incident_fixes.py`.

## 2. The swallowed 401 (PR #59)
Setting `SILK_API_KEY` — a protective change — made the agent-settings panel silently
show a stale legacy 14-agent list forever. **Root cause:** an empty `catch` in
`web/index.html loadAgentCatalog()` swallowed the new 401. **Fix:** explicit
catalog status (ok/unauthorized/error) + visible red warning.
**THE RULE:** every UI fetch failure sets a visible status; a protective change can
convert a silent-error path into a permanent silent regression.
**Guard:** `tests/test_wave7_agent_panel_fallback.py`.

## 3. Fenced JSON dropped real findings (wave 8, PR #60)
An observed Albert Heijn 9.96€/kg price — real, cited evidence — vanished from the
report. **Root cause:** `_parse_output` took first `{` to last `}` over the whole
reply; a ```json fence plus a trailing comment containing a brace corrupted
extraction and dropped the entire reply. The SAME bug existed copy-pasted in FIVE
places in `silk_ai_judge.py`. **Fix:** `_json_candidates()` tries each fence in
isolation first (`silk_llm_runtime.py:480`); one shared `_extract_json` in
`silk_ai_judge.py`. **THE RULE:** never brace-scan LLM output; when you fix a parse
bug, grep for its copy-pasted siblings before closing.
**Guard:** `tests/test_wave8_live_tuning.py`.

## 4. The CSV comment-line bug (wave 8)
Netherlands Muslim-share reported "missing" — the data existed in the CSV.
**Root cause:** the runtime `_load_csv` didn't skip `#` comment lines, shifting the
header so `iso3` lookups failed for EVERY row of two tables, ALL markets. The correct
loader already existed — in a test helper that never reached runtime.
**THE RULE:** shared parsing lives in runtime code; a test helper that "fixes" input
handling is a smell that the runtime is broken.
**Guard:** `tests/test_wave6_reference_csvs.py`.

## 5. Case-sensitive category binning (wave 9, PR #61)
All 5 analyst intersections said "دليل غير كافٍ" while the same report showed real
evidence. **Root cause:** Claude returned `"Demand"`; the analyst matched `"demand"`
exactly — findings binned into no-category. **Fix:** normalized (lowercase+strip)
matching (`silk_market_analyst.py:133-140`).
**THE RULE:** normalize EVERY enum-like value an LLM returns before matching on it.

## 6. Computed but unwired (PR #66)
Owner: report reads as «أرقام منفصلة بلا معنى». **Root cause (one of two):**
`ai_report()` computed a Claude executive summary per analysis — and dropped it on
the floor; nothing wired it into `build_view` or any export. (The other: raw
confidence decimals leaking through a shared helper across ~10 report call sites.)
**THE RULE:** unwired output is a failure class distinct from broken output. After
computing anything, grep for its consumer the same day. (Same class: wave-9
`product_card` accepted by pydantic, consumed by nothing.)

## 7. The 60s timeout blamed on a missing key (PR #69)
Live run: 5 intersections "insufficient", no report — dashboard said "requires Claude
key" although **29 other Claude calls succeeded in the same run**. **Root cause:**
analyst/writer payloads span all 12 missions and blew the fixed 60s timeout; the
None-return was conflated with keylessness; the quality gate short-circuited on
empty report text and PASSED the worst possible outcome. **Fix:**
`SILK_AI_LONG_TIMEOUT_S=300` for analyst/writer only; `failure_reason()`
distinguishing no-key vs call-failure; gate check `analyst_layer_failed` that FAILs.
**THE RULE:** size timeout budgets to payloads; attribute failures only from captured
evidence; a gate that cannot see the worst outcome is worse than no gate.
**Guard:** `tests/test_wave_p1_ai_timeout_and_failure_reasons.py`.

## 8. Three strikes, then instrumentation — STILL OPEN (PRs #70, #71)
The writer failed three times across live runs with the same generic "timeout or
network error". **The fix was a refusal to guess:** instead of choosing between
candidate fixes (wider timeout? streaming?), PR #71 built evidence capture —
`silk_llm_provider.last_error()` contextvar with real exception type/HTTP
status/body, connect/read timeout split so ConnectTimeout vs ReadTimeout
self-identifies the phase, and traced `report_call` events with `elapsed_ms`.
**THE RULE:** when a live failure has no evidence, ship instrumentation, not a guess.
**Status:** unresolved — see `.claude/skills/writer-timeout-open-case/SKILL.md`.

## 9. Juice shops presented as importers (live review 2)
Owner: «يستخدم محلات العصير العادية ويقول انهم مستوردين». **Root cause:** Google
Places `types` was ignored — retail/food-service entities were listed as
importers/distributors. Also: hardcoded default years (2022 engine / 2023 UI);
owner: «البيانات قديمة يمديك الى 2024». **Fix:** `types` extraction +
`_business_hint` classification, retail excluded with the dropped count declared,
⚠ retail warning in report and UI; years computed from today (`_default_year()`).
**THE RULE:** classify entities before presenting them as something; never hardcode
a year — compute from today.
**Guard:** `tests/test_live_report_findings2.py`.

## 10. The 61× self-contradiction (honey/Kuwait)
One report showed market_size $789,206 next to a competitor table summing $48.5M.
**Root cause:** the Comtrade world row was taken as truth even when smaller than the
sum of its own partner rows — arithmetically impossible. **Fix:** market size =
max(world row, partner sum); >20% divergence appends `xval_note` and drops
competitor confidence 0.9→0.7 (`silk_data_layer_v2.py` world/grand reconciliation).
**THE RULE:** cross-validate every total against its own parts before presenting;
a source can be authoritative and still internally inconsistent.
**Guard:** `tests/test_project_review_fixes.py`.

## 11. The credit-burning mid-flight loss (PR #65)
A live /research run died mid-flight: 11/12 successful missions lost, clients
retried from scratch — double Claude spend, zero usable output. Also found: the
/research persist path hardcoded `"data/silk.db"`, ignoring `SILK_DATA_DIR` — on
Railway, results were written to the ephemeral disk, not the volume.
**Fix:** per-mission checkpoint the moment it completes; `resume=<id>` re-runs only
missing missions; `async_run` decouples request from run; env-aware paths everywhere.
**THE RULE:** checkpoint incrementally as work completes; request ≠ run; every
storage access resolves through the env-aware path helpers, never a literal path.
**Guard:** `tests/test_wave13_resilience.py`, `tests/test_persistent_volume.py`.

## 12. The fail-open money guard (security audit, PR #31)
A corrupt `usage.db` meant the paid cap allowed UNLIMITED spend — the error branch
returned "allowed". **Fix:** fail-closed on any DB error
(`silk_usage.try_reserve_paid_calls`, `silk_usage.py:118+`).
**THE RULE:** guards that protect money fail closed. Also from the same audit:
unauthenticated enumerable `/analyses` leaked customer cost cards; the rate limiter
must never evict the current identity's own counter.

## 13. Contextvars vs threads (wave 6 build)
Agent prefs and AI-extras blocking were silently ignored inside the 11 parallel
missions. **Root cause:** `ThreadPoolExecutor` does not inherit contextvars; and one
`Context` object cannot `.run()` from two threads (RuntimeError). A third variant:
a leftover `_data_counter` contextvar leaked across pytest tests and falsely tripped
the global LLM cap. **Fix:** per-task `contextvars.copy_context()`
(`silk_missions.py:345-351`); autouse conftest reset.
**THE RULE:** any new thread/pool copies context per task; any new contextvar gets
an autouse reset fixture the same day.

---

## Pre-mortem checklist (run before shipping any change)

1. Which endpoint/path produces the output I changed — and did I verify on THAT path? (#1)
2. Did I add any catch/except that swallows without setting visible status? (#2)
3. Does my change parse LLM output anywhere? Am I reusing `_extract_json`/`_json_candidates`? Did I grep for copy-pasted siblings? (#3)
4. Does runtime parsing depend on input hygiene that only a test helper handles? (#4)
5. Do I match on any LLM-returned label without normalizing? (#5)
6. Everything I compute — who consumes it? Grep for the consumer. (#6)
7. Any new Claude call: which timeout budget, and will `failure_reason` attribute its failure correctly? (#7)
8. If this "fixes" a live failure — do I have captured evidence, or am I guessing? (#8)
9. Any entity/label presented to the user — is it classified, or assumed? Any date/year — computed or hardcoded? (#9)
10. Any total I present — does it cross-validate against its own parts? (#10)
11. Long-running work — does it checkpoint incrementally? Storage — env-aware paths? (#11)
12. Any guard error branch — does it fail closed? (#12)
13. Any new thread — `copy_context()`? Any new contextvar — reset fixture? (#13)

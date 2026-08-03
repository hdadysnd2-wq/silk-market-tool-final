# مكتبة المهارات — Skill library

Knowledge-transfer library from the departing principal engineer (2026-07).
Written so that any model/engineer can operate this codebase mechanically and
still match the departing engineer's judgment. Weighted — per the owner's
explicit priorities — toward **report quality, output accuracy, and
operator-intent fidelity** first, code hygiene second.

مكتبة نقل معرفة من المهندس الرئيسي المغادر. مرجّحة حسب أولويات المالك:
جودة التقارير، دقة المخرجات، وتنفيذ نيّة المشغّل بأمانة.

## Start here

| Situation | Skill |
|---|---|
| Orienting on the codebase / any multi-module task | `architecture-map` |
| The owner says the output ignores his written instructions | `operator-intent-fidelity` |
| A /research report is poor, unconvincing, or leaking internals | `research-report-quality` |
| A /research run failed, hung, or a mission came back empty | `research-debugging` |
| The report writer returned `report=None` again (OPEN incident) | `writer-timeout-open-case` |
| About to do anything that spends paid credits | `credit-economics` |
| Editing any mission/analyst/writer prompt | `mission-tuning-and-evals` |
| An /analyze result looks wrong, empty, stale, or inconsistent | `analyze-pipeline-debugging` |
| Touching silk_render.py / silk_reports.py / web/index.html | `render-view-and-reports` |
| Designing or reviewing ANY change | `change-rules` |
| A symptom feels familiar / before shipping non-trivial work | `failure-stories` |
| Writing or modifying tests | `testing-discipline` |
| Deploying, env vars, production-only behavior | `railway-operations` |
| Opening a PR or documenting an incident/decision | `pr-and-wave-discipline` |
| The owner pastes real evidence and asks "why did this happen" / touching the money path, sanitizer chain, or `/ops` endpoints | `silk-operations` |

## The three laws that outrank everything in this library

1. **Never fabricate** — a missing value is `None + confidence 0.0 + declared
   note`, never a guess, never a default (CLAUDE.md, the founding principle).
2. **Evidence before fixes** — reproduce via trace/tests, label your evidence
   class; when there is no evidence, ship instrumentation, not a guess.
3. **Spend down the cheap-first ladder** — hermetic tests → single-mission dry
   run → report regen → resume → full run. A full /research costs ~$2 of the
   owner's money.

## Known open items handed over

- **Writer-timeout case is RESOLVED** (root cause found from the Netherlands
  evidence: `max_tokens` output-budget exhaustion) — see
  `writer-timeout-open-case` for the fix and the protocol it leaves behind for
  the next *different* writer failure (a new `error_type` is a new case, not a
  reopening of this one).
- `evals/golden_cases.json` is deliberately `[]` — the first golden case
  requires a manually verified live Comtrade number (runbook in
  `docs/DEEP_RESEARCH_DECISIONS.md`).
- The owner's standing complaint — "the output lacks intelligence; it doesn't
  execute what I write" — is the library's organizing problem. Start with
  `operator-intent-fidelity` §3 (which lever for which intent) and
  `research-report-quality` §2 (which layer for which symptom).

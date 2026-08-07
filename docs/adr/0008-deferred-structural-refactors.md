# ADR 0008 — Engine structural refactors: deferred, with a plan

**Status:** Accepted · **Date:** 2026-08-07 · **Context:** `docs/audits/CODE_AUDIT_2026-08-07.md` §3 (architecture)

## Context

The 2026-08-07 audit's architecture pass flagged three engine-side structural
debts and recommended tackling them "opportunistically / when next touched":

1. **Flat root namespace.** `packages/silk_intel` installs 72 modules into the
   *root* Python namespace (`pyproject.toml` `py-modules`), including generically
   named `api`, `correlation`, `fix_agent`. There is no `silk_intel.` package
   prefix, so any future top-level collision is silent.
2. **God-files.** `silk_reports.py` (4,883 lines), the superseded standalone
   `api.py` (3,355), `silk_render.py` (2,469).
3. **Source-grep lock tests.** ~120 assertions grep the *source text* of those
   files (e.g. `"_free_ai_extras_allowed()" in _src("api.py")`), pinning function
   names and layout so the god-files effectively cannot be decomposed without a
   test rewrite.

## Decision

**Defer all three as a single coordinated refactor, not piecemeal in this
remediation.** The remediation branch (`claude/pre-launch-codebase-audit-…`)
delivered the launch-blocking fixes and the Factory Report Journey; these three
are correctness-neutral engineering debt, and doing them *partially* is worse
than not starting:

- The namespace migration must rename 72 modules and rewrite every import across
  the engine, the body's `services/engine.py` seam, **and** the ~2,578-test
  hermetic suite in one atomic change — a half-migrated tree imports both `api`
  and `silk_intel.api` and is more fragile than either endpoint.
- `silk_reports.py` cannot be split while the source-grep tests pin its current
  layout; the tests must be converted to behavioral assertions *first*, and that
  conversion is the actual unit of work — a few extracted helpers behind the
  still-grepping tests buys nothing.

Attempting these under the launch-remediation deadline would risk destabilizing
a green 2,578-test suite for zero behavior change. They are therefore scheduled
as a **post-launch structural sprint**, tracked here.

## The plan (post-launch sprint, in order)

1. **Convert source-grep tests to behavioral tests.** For each `_src(...)`
   assertion, replace "this string appears in the file" with "this behavior
   holds" (call the function, assert the outcome). Add a harness rule (already
   drafted in the audit) that no new `_src`-style test may be added. This
   unblocks everything below.
2. **Introduce the `silk_intel.` package namespace** with a one-release
   compatibility shim (`import silk_intel.foo as foo`) so the body and tests
   migrate incrementally, then drop the root `py-modules` and the shim. Rename
   `api.py`→`legacy_server.py` (or delete — see ADR 0004's retirement of the
   standalone product) and `correlation`/`fix_agent` under the package.
3. **Decompose `silk_reports.py`** along its natural seams (view-model builders,
   docx renderers, PDF renderers, sanitizers) now that its tests assert behavior,
   not layout. Same for `silk_render.py`.
4. **Full `print()`→structlog sweep** across the ~125 engine `print()` sites that
   bypass the worker's JSON logging (partially mitigated today: the body is
   clean; the engine's prints are in library modules the worker imports). This
   rides along with the decomposition since it touches the same files.

## Consequences

- No behavior change now; the debt is documented, bounded, and sequenced instead
  of half-addressed.
- The launch-readiness score treats these as **known, non-blocking** debt (they
  tax future engine changes but do not break at launch).
- ADR 0004's retirement of the standalone `silk_platform`/`api.py` product should
  be executed together with step 2 (the namespace migration is the natural point
  to delete the legacy server for good).

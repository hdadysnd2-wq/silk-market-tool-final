# ADR-0004 — The vendored `silk_platform` is locked out of the product

**Status:** accepted (2026-08-05) · **Relates to:** invariant I3; KILL list; audit H-5/№10

## Context

`packages/silk_intel/silk_intel/silk_platform/` (29 modules) is the engine's
legacy standalone tenant console, vendored with the engine to keep its hermetic
test suite green. It contains a complete second cold-send pipeline (own SQLite
`email_queue` → SMTP) whose enqueue path has **no per-email human approval
gate** — the only send path in the repository outside the I3 three-layer state
machine.

It is currently unreachable from the product: nothing under `apps/` imports it,
and the deployment builds only `apps/api` + `apps/web` (the engine's standalone
`api.py`, which mounts it, is an opt-in `standalone` extra that is never
deployed). But "unreachable by accident" is not a guarantee.

## Decision

1. **The product must never wire `silk_platform`.** This is now a hard,
   test-enforced invariant: `apps/api/tests/test_no_silk_platform_import.py`
   fails the suite if any module under `apps/api/app` imports it.
2. All cold outreach continues to flow exclusively through the I3 state machine
   (`services/approval.py` → `services/sending.py`).
3. **Retiring `silk_platform` outright is deferred** to the same Phase-4 session
   that retires the engine's static `web/` (both are load-bearing for vendored
   engine tests) — tracked in `docs/BACKLOG.md`.

## Consequences

- The unapproved send path stays dead code in the deployed product, provably.
- Engine tests that exercise `silk_platform` internals keep passing untouched
  (the merge invariant "engine tests stay green / move unchanged" holds).
- When Phase 4 retires it, this ADR and the guard test document why it existed.

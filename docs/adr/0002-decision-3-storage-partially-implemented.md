# ADR-0002 — Locked decision #3 (storage on Postgres) is OPEN, not complete

- **Status:** Accepted
- **Date:** 2026-08-04
- **Deciders:** Owner (recorded confirmation)
- **Relates to:** [ADR-0001](0001-master-prompt-governs.md) · Master Prompt locked decision #3

## Context

The Master Prompt's locked decision #3 reads: *"Storage unified on PostgreSQL.
Repo A's SQLite + disk cache are replaced by Postgres + Redis. Write a thin
adapter behind Repo A's existing `silk_storage` interface."*

ADR-0001 fixes the Master Prompt as governing and records that decisions found to
be only partially implemented must be stated honestly rather than presented as
complete. An audit of the merged `main` found decision #3 is exactly such a case,
so this ADR reclassifies its status on the record.

## Decision

**Locked decision #3 is reclassified from "locked / done" to "OPEN — partially
implemented."** It remains the intended architecture (this ADR does **not**
reverse it); it is simply not finished.

What is done, and what is not:

- **Done — the product shell.** `apps/api` persists through SQLAlchemy to
  PostgreSQL and uses Redis for Celery and cache. There is no SQLite in the hot
  request path (enforced/observed across the API test suite). The unified
  `DataPoint`/`ProviderRecord` contract (decision #4) is in place.
- **Open — the engine-side adapter.** The vendored engine
  (`packages/silk_intel`) still uses its own SQLite + disk-cache implementation
  behind the `silk_storage` interface. The "thin adapter behind `silk_storage`
  that persists through Postgres" has **not** been written; the engine's store is
  retained as a legacy shim.

## Scope guard

The `silk_storage` → Postgres conformance adapter is deferred to a **dedicated
storage-conformance session**. It must **not** be built as a side effect of an
unrelated change: it touches the engine's storage contract (which carries its own
hermetic tests and a store-first freshness/staleness model) and needs its own
focused branch, test parity, and review. Until then the engine's SQLite/disk
store stays in place and is not presented as Postgres-backed.

## Consequences

- The status trail is consistent across the record: `docs/architecture.md`
  (Storage & contracts) and `docs/BACKLOG.md` (the open engine-storage item) both
  state decision #3 is partial and point here for the formal reclassification.
- No code changes accompany this ADR. It records status only; the adapter itself
  is future work under the scope guard above.
- When the adapter lands, this ADR is updated (or superseded) to mark decision #3
  fully implemented.

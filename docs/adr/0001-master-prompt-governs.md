# ADR-0001 — The Master Prompt governs the Silk United merge

- **Status:** Accepted
- **Date:** 2026-08-04
- **Deciders:** Owner (recorded confirmation)

## Context

Silk United is the merge of two repositories — the market-intelligence engine
(Repo A, "the brain", now `packages/silk_intel/`) and the product shell + campaign
machinery + Arabic RTL web app (Repo B, "the body", now `apps/api/` + `apps/web/`).
A single, binding reference is needed so that architecture decisions and safety
guardrails are not re-litigated per pull request, and so that any reviewer (human
or agent) can check a change against one authority.

## Decision

**`docs/MASTER_PROMPT.md` is the canonical governing document for this repository.**

- Its **locked architecture decisions** (modular monolith on the Repo B skeleton;
  engine as an in-process package; storage on Postgres + Redis; one unified
  `DataPoint`/`ProviderRecord` contract; the external-tool verdicts; leads single
  primary provider; brief-first reports; auto-year handling) are binding.
- Its **non-negotiable invariants I1–I10** are binding and may not be weakened or
  bypassed by any code path:
  - I1 no fabricated data · I2 mandatory human HS-confirm gate · I3 3-layer human
    campaign-approval gate · I4 cross-tenant suppression + append-only audit ·
    I5 paid agents only inside the deepen context · I6 no cold outreach via a
    transactional ESP · I7 pandas confined to `etl/` · I8 lawful-basis per lead
    (PDPL Art. 25 / GDPR LIA / CAN-SPAM) · I9 transit-port guard in world ranking ·
    I10 Arabic RTL-first UI via next-intl.

Any change that would alter a locked decision or an invariant requires a **new,
superseding ADR** that references this one — not an inline edit and not a PR-level
exception.

## Governance model

- **`main` is the single source of truth.** All work lands on `main` via
  short-lived increment branches and pull requests; there are no long-lived merge
  branches.
- Every pull request keeps CI green, including the vendored engine's hermetic
  suite (a hard merge invariant: the engine tests move unchanged).
- The phased execution plan (Phases 0–4) in the Master Prompt sequences the work;
  live provider keys are activated one at a time only after the pre-go-live gate
  items are complete.

## Consequences

- Reviewers check changes against the Master Prompt's invariants directly.
- Decisions that are found to be only partially implemented are recorded honestly
  (see the decisions log / backlog and any superseding ADRs) rather than being
  presented as complete.
- This ADR does not itself implement anything; it fixes the authority and the
  governance model so subsequent increments can be judged against them.

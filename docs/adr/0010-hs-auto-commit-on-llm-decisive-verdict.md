# ADR-0010 — HS auto-commit extended to the engine's LLM-decisive verdict

- **Status:** accepted (owner decision, 2026-08-08 — third recurrence of the
  «still requires manual selection» complaint)
- **Amends:** ADR-0009 (and, through it, invariant I2 in `docs/MASTER_PROMPT.md`)

## Context

ADR-0009 auto-commits `product.hs_code` only on the engine's strict
`tier="auto"` verdict, whose decisiveness threshold is anchored on the
engine's *partial seed CSV* (`seed_overlap ≥ SILK_HS_AUTO_MIN_OVERLAP`,
engine lesson 80). That anchoring is structurally unreachable for exactly the
products the owner cares about: whenever label evidence moves a product out of
its bare-name heading (flavoured milk → the beverages heading), the correct
code lives *outside* the seed, its seed overlap can never reach the bar, and
the intake stops at the candidate picker no matter how unambiguous the model's
verdict was. Live evidence (strawberry-milk journey, worker log 2026-08-08):
`tier="candidates"`, three proposals at 50%, and the owner reporting for the
third time that *«the agent still does not automatically identify the product
code without manual selection»*.

## Decision

1. The engine's `classify_general` gains a second, tagged route to
   `tier="auto"`: the **LLM-decisive verdict** (`source="llm_decisive"`). It
   fires only when ALL of the following hold:
   - the LLM consultation actually happened (live or cache — lesson 79's
     downgrade stays untouched);
   - the model **explicitly declared** `decisive: true` in its reply (a new
     prompt contract; absence of the field — every cached v2 reply — is never
     decisive, and the classify-policy cache version is bumped so stale slates
     recompute);
   - the model's #1 candidate carries `confidence ≥ SILK_HS_LLM_AUTO_MIN_CONF`
     (default 0.8) **and** beats the model's #2 by
     `SILK_HS_LLM_AUTO_MARGIN` (default 0.15) — a decisive claim with
     contradicting confidences is rejected;
   - that same candidate **survived the deterministic structural gate**
     (real WCO chapter, no domain exclusion, no fabricated code — I1) and
     ranks first in the merged displayed pool above the candidate display
     threshold.
2. The platform commit machinery is unchanged: `classify_product` commits on
   `tier="auto"` exactly as under ADR-0009 — `hs_auto_classified=True`
   provenance tag, never over a human confirmation, human confirm/override
   clears the tag and feeds `HSCorrection`.
3. Kill switch: `SILK_HS_LLM_AUTO=0` restores the seed-anchored strict gate as
   the only auto path.

## Residual risk, accepted by the owner

Lesson 80 (a model-authored *description* must not lexically self-certify
through the seed-anchored overlap gate) remains enforced verbatim for the
seed-anchored route. This decision knowingly adds a route in which the
model's **declared verdict** — not its text smuggled through a lexical gate —
commits a code with zero human clicks. A successfully injected image label
could therefore steer an auto-commit. Defenses that remain: `_isolate()`
around all label text, the structural no-fabrication gate, the
confidence+margin contradiction check, the visible «صُنّف تلقائيًا» badge with
one-click override, the correction ledger learning from overrides, and the
bounded downstream funnel (per-sweep Comtrade cap). The owner, presented with
the trade-off (ADR-0009 already records the same choice for the strict tier),
chose zero-click automation.

## Consequences

- The strawberry-milk class of products (label evidence + decisive model
  verdict) goes image → committed code → world funnel with zero clicks;
  genuinely contested verdicts (close confidences, or the model declining to
  declare decisiveness) still stop at the picker.
- Rollback: set `SILK_HS_LLM_AUTO=0` (behavioral), or revert the engine
  decisive-gate commit; the platform layer needs no change either way.

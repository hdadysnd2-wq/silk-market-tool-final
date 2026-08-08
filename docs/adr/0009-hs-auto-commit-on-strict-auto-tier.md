# ADR-0009 — HS auto-commit on the engine's strict `tier="auto"` verdict

- **Status:** accepted (owner decision, 2026-08-08)
- **Amends:** invariant I2 (`docs/MASTER_PROMPT.md`)

## Context

The intake pipeline reads the product image (vision pass → attributes), feeds
those label signals to the engine's single HS classifier, and — before this
decision — only ever PROPOSED candidates: every product required a human click
to commit `hs_code`, even when the engine's verdict was structurally
unambiguous. The owner asked (in the strawberry-milk journey follow-up): *«ليش
ما تخليه يقرأ الصورة ويحدد الكود تلقائي»* — why not let it read the image and
set the code automatically — and, offered the explicit trade-off, chose full
auto-commit over one-click confirmation.

## Decision

1. When `classify_general` returns its STRICT `tier="auto"` verdict (verified
   top candidate anchored on the seed, overlap ≥ `SILK_HS_AUTO_MIN_OVERLAP`,
   clear margin over the runner-up — genuine ambiguity structurally never
   passes), `classify_product` commits `product.hs_code` immediately.
2. The commit is provenance-tagged `hs_auto_classified=True` — a NEW column,
   distinct from `hs_confirmed_by_user`, which remains **human-only** and is
   still written solely by `confirm_hs_code`.
3. Guards, in order of supremacy:
   - a human-confirmed code is NEVER overwritten by re-classification;
   - a human confirm/override clears the auto tag and, when it changes an
     auto-committed code, records an `HSCorrection` with the machine's code as
     `suggested` (classifier feedback);
   - the engine never returns `tier="auto"` when label/image signals are
     present but the LLM consultation did not actually happen (valve off, no
     key, budget reservation denied, call failure) — it downgrades to
     `tier="candidates"` and logs the downgrade (engine LESSONS row 79,
     locked test-first). Name-only evidence cannot auto-commit a product
     whose label was described.
4. Downstream gates (world funnel, report/buyers links) accept an
   auto-committed code exactly like a confirmed one; the UI badges it
   «صُنّف تلقائيًا» with the override path one click away.

## Consequences

- Unambiguous products (e.g. plain dates) go image → committed code → funnel
  with zero clicks. Ambiguous ones (e.g. flavoured milk, 2202 vs 0402) still
  stop at the candidate picker — the strict gate, not optimism, decides.
- The correction ledger keeps learning from human overrides of auto commits.
- Rollback is `alembic downgrade` of 0023 plus reverting the service commit
  block; the engine downgrade rule (lesson 79) stays — it is correct
  independently of this feature.

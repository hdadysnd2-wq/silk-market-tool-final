# Backlog — deferred increments (tracked, not lost)

Items consciously deferred during the governance-first consolidation onto `main`.
Each is a future short-lived-branch increment, sequenced after the pre-go-live
gate items. Recording them here so nothing unique is silently dropped.

## From closed PR #39 — real per-unit cost input (`Product.cost_per_unit`)

`main` computes competitor margins as **estimated gross headroom** (observed
competitor price vs. a modeled cost). PR #39 (closed as a superseded margin
variant — it duplicated `services/margin.py` and collided with the `0009`
migration) carried one distinct idea worth keeping: a **real factory-supplied
`Product.cost_per_unit`** so the margin thread can show an *actual* margin, not an
estimate.

- **Scope when picked up:** add a nullable `cost_per_unit` column to `Product`
  (its own migration on top of `main`'s current head — no `0009` collision), let
  the product form capture it, and have `services/margin.py` prefer the real cost
  when present and fall back to the estimate otherwise (still returning the
  unified contract envelope, I1). One classifier / one margin service — do **not**
  re-introduce a second `margins.py`.

## Deferred — retire the engine's static `web/` + `netlify.toml` (KILL-after-P2)

The Master Prompt lists Repo A's static `web/` and Netlify config for removal.
This is **not** a trivial delete: **30 vendored engine tests** unconditionally
`open()` and assert on `web/index.html`, `web/platform.html`, and `web/fonts/`
(e.g. `test_wave1_hs_classifier`, `test_stage5_report`, `test_selfhosted_fonts`,
`test_platform_ui_page`, `test_ui_audit_high_fixes` runs Node on blocks extracted
from `web/index.html`), and `api.py` mounts `web/` as StaticFiles. `netlify.toml`
merely publishes that same `web/` dir.

Deleting `web/` now would turn the engine hermetic suite red, violating the hard
"engine tests stay green / move unchanged" merge invariant. Retirement therefore
belongs to a **dedicated Phase-4 session** that removes the static frontend *and*
retires/ports its 30 guard tests together (the Streamlit/dev console stays as the
internal tool). Until then `web/` and `netlify.toml` remain.

## Open — engine-side `silk_storage` → Postgres adapter (locked decision #3)

Decision #3 ("storage unified on Postgres; write a thin adapter behind Repo A's
`silk_storage` interface") is **partially** implemented: the product shell
(`apps/api`) is fully on Postgres + Redis, but the vendored engine still uses its
own SQLite/disk implementation behind `silk_storage`. The conformance adapter is
deferred to a dedicated storage session (do not build it as a side effect of an
unrelated change). See [ADR-0002](adr/0002-decision-3-storage-partially-implemented.md)
for the formal reclassification of decision #3 as OPEN.

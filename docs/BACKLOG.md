# Backlog — deferred increments (tracked, not lost)

Items consciously deferred during the governance-first consolidation onto `main`.
Each is a future short-lived-branch increment, sequenced after the pre-go-live
gate items. Recording them here so nothing unique is silently dropped.

## ✅ DONE — real per-unit cost input (`Product.cost_per_unit`) (from closed PR #39)

`main` previously computed competitor margins only as **estimated gross headroom**
(observed competitor price vs. the offer-price midpoint). PR #39 (closed as a
superseded margin variant — it duplicated `services/margin.py` and collided with
the `0009` migration) carried one distinct idea worth keeping: a **real
factory-supplied `Product.cost_per_unit`** so the margin thread can show an
*actual* margin, not an estimate.

- **Delivered:** nullable `cost_per_unit` column on `Product` (migration `0015`,
  on top of `0014` — no `0009` collision); captured by the product create form
  (API multipart + the web upload dialog); `services/margin.py` now prefers the
  real cost when present and falls back to the offer estimate otherwise, reporting
  which via `margin_basis` (`actual_cost` / `offer_estimate` / `null`) and spelling
  it out in the limits (still the unified declared-gap envelope, I1). One margin
  service — no second `margins.py`.

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

## Deferred — retire `silk_platform` (KILL-list residue; locked out, see ADR-0004)

The vendored engine ships `silk_platform/` — a legacy standalone console with
its own cold-send queue that bypasses the I3 approval state machine. It is now
**locked out of the product by a hard test**
(`apps/api/tests/test_no_silk_platform_import.py`) and is not part of any
deployed build. Actual deletion is deferred to the same Phase-4 session that
retires the engine's static `web/` (both are load-bearing for vendored engine
tests). See [ADR-0004](adr/0004-silk-platform-lockout.md).

## Deferred — consolidate the funnel brief/report onto `build_view` (H-5, ADR-0003)

The platform's funnel brief (`services/funnel_brief.py`) and JSON/HTML report
(`services/report.py`) are platform-native rather than `build_view`-derived
(only the Word export goes through the engine). Decision #7's non-negotiables
are pinned by tests on the platform path; full consolidation is a dedicated
future session. See [ADR-0003](adr/0003-canonical-report-path-h5.md). Related
smaller items recorded there: the engine's legacy API still accepts a caller
year (`api.py` `AnalyzeRequest.year`) — the product never exposes it; and the
two transit-hub penalties are intentionally different magnitudes (engine fine
ranking 0.25 vs Stage-1 coarse screen 0.5), each documented at its constant.

## Open — engine-side `silk_storage` → Postgres adapter (locked decision #3)

Decision #3 ("storage unified on Postgres; write a thin adapter behind Repo A's
`silk_storage` interface") is **partially** implemented: the product shell
(`apps/api`) is fully on Postgres + Redis, but the vendored engine still uses its
own SQLite/disk implementation behind `silk_storage`. The conformance adapter is
deferred to a dedicated storage session (do not build it as a side effect of an
unrelated change). See [ADR-0002](adr/0002-decision-3-storage-partially-implemented.md)
for the formal reclassification of decision #3 as OPEN.

# ADR-0003 — One canonical analysis/report path; funnel brief consolidation deferred

**Status:** accepted (2026-08-05) · **Relates to:** locked decisions #2 and #7; audit finding H-5

## Context

The master prompt's locked decision #7 requires both report surfaces (one-page
brief + full Word) to derive ONLY from the engine's unified template
(`silk_render.build_view`). Reality after the merge:

- The **Word export** does derive from the engine (`apps/api/app/api/reports.py`
  → `services/report_view.py` → `build_view` → `render_docx`). ✅
- The **funnel brief** (`services/funnel_brief.py`) and the JSON/HTML product
  report (`services/report.py`) are platform-native builders over the funnel's
  Postgres rows. They honour decision #7's non-negotiables (a source line under
  every figure; a "limits of this report" section; the funnel transparency
  line) but do not pass through `build_view`.

A full consolidation would mean either teaching `build_view` the 3-stage-funnel
shape or rebuilding the funnel brief inside the engine — a cross-cutting
rewrite the master prompt's own working agreements forbid doing as a big bang.

## Decision

1. **The canonical product path is `apps/api`** — its funnel pipeline, brief and
   report are what the shipped UI serves. The engine's `/analyze` surface stays
   the analytical core (HS resolve, ranking primitives, docx rendering) consumed
   via direct imports.
2. The **decision #7 non-negotiables are pinned by tests** on the platform path
   (source lines, limits section, funnel transparency including the shortlist
   step) so the two builders cannot silently diverge on the parts that matter.
3. **Full brief/report consolidation onto `build_view` is DEFERRED** to a
   dedicated session, tracked in `docs/BACKLOG.md` — not done opportunistically.

## Consequences

- A fix in the engine's report layer does not automatically propagate to the
  platform brief (the H-5 risk); the pinned-invariant tests bound that risk to
  cosmetics rather than compliance.
- Anyone touching `services/funnel_brief.py` / `services/report.py` must keep
  the pinned invariants green and should consult this ADR before adding a third
  builder — that is the forbidden direction.

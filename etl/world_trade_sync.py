"""Bulk refresh of the ``world_trade`` table — Stage 1 of the world funnel.

Screens every importer in the world for a given HS6 from a *precomputed* table
so Stage 1 costs zero live API calls. This job precomputes that table from UN
Comtrade bulk endpoints (via ``comtradeapicall``), computing YoY growth and the
3-year CAGR, and applying the transit-port guard (invariant I9): re-export hubs
(AE, NL, SG, HK, BE, …) have their import volumes inflated by transshipment, so
their rows are tagged ``is_transit_hub`` and carry a visible penalty rather than
silently topping the ranking. Mirror-derived rows are tagged ``is_mirror``.

pandas + comtradeapicall live HERE ONLY (I7). They are imported lazily inside
``run()`` so this module stays importable without them and the repo-wide
no-pandas guard is satisfied everywhere else.

Phase 0: documented skeleton. The ``world_trade`` migration, the Stage-1 query
and the transit-hub fixture test land in Phase 2; first live sync in Phase 3.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

# Re-export hubs whose import volumes are inflated by re-export / transshipment.
# Kept in sync with the ranking guard (invariant I9).
TRANSIT_HUBS: frozenset[str] = frozenset({"ARE", "NLD", "SGP", "HKG", "BEL"})

# Target table columns (materialised by the Phase 2 Alembic migration):
#   hs6, importer_iso3, year, import_usd, import_qty, yoy_growth, cagr_3y,
#   is_mirror, is_transit_hub, source, fetched_at
WORLD_TRADE_COLUMNS: tuple[str, ...] = (
    "hs6",
    "importer_iso3",
    "year",
    "import_usd",
    "import_qty",
    "yoy_growth",
    "cagr_3y",
    "is_mirror",
    "is_transit_hub",
    "source",
    "fetched_at",
)


# ---------------------------------------------------------------------------
# Pure transform helpers — no pandas, no network. These turn raw yearly import
# series into ``world_trade`` rows (the Stage-1 screening table): computing
# year-over-year growth and the 3-year CAGR, and tagging transit hubs (I9). The
# bulk Comtrade DOWNLOAD (pandas + comtradeapicall) stays in ``run()`` and is the
# Phase-3 live piece; these helpers are hermetically testable today.
# ---------------------------------------------------------------------------


def is_transit_hub(importer_iso3: str) -> bool:
    """Whether an importer is a re-export hub whose imports include re-exports (I9)."""
    return (importer_iso3 or "").upper() in TRANSIT_HUBS


def compute_yoy(series: dict[int, float | None]) -> float | None:
    """Year-over-year growth as a fraction from the two most recent years.

    ``None`` when there are fewer than two usable years or the base is zero — a
    gap is declared, never fabricated (I1).
    """
    years = sorted(y for y, v in series.items() if v is not None)
    if len(years) < 2:
        return None
    latest, prev = series[years[-1]], series[years[-2]]
    if not prev:  # zero or falsy base → undefined growth
        return None
    return (float(latest) - float(prev)) / float(prev)


def compute_cagr_3y(series: dict[int, float | None]) -> float | None:
    """Compound annual growth rate over the last ~3 years, as a fraction.

    Uses the most recent year and the year ~3 back (or the earliest available
    spanning ≥2 years). ``None`` when insufficient/degenerate (I1).
    """
    years = sorted(y for y, v in series.items() if v is not None and v > 0)
    if len(years) < 2:
        return None
    end_year = years[-1]
    start_year = max((y for y in years if y <= end_year - 3), default=years[0])
    span = end_year - start_year
    if span <= 0:
        return None
    ratio = float(series[end_year]) / float(series[start_year])
    return ratio ** (1.0 / span) - 1.0


def build_rows(
    hs6: str,
    imports_usd: dict[str, dict[int, float | None]],
    *,
    source: str = "UN Comtrade",
    fetched_at: str | None = None,
    mirror_importers: set[str] | None = None,
    qty: dict[str, dict[int, float | None]] | None = None,
) -> list[dict]:
    """Turn per-importer yearly import series into latest-year ``world_trade`` rows.

    ``imports_usd`` maps ISO3 → {year: import_usd}. One row is emitted per importer
    for its latest year, carrying computed ``yoy_growth``/``cagr_3y`` and the
    ``is_transit_hub`` (I9) / ``is_mirror`` provenance flags. Rows are ready to
    upsert into ``world_trade`` (keys match ``WORLD_TRADE_COLUMNS``).
    """
    mirror = {m.upper() for m in (mirror_importers or set())}
    rows: list[dict] = []
    for iso3, series in imports_usd.items():
        usable_years = [y for y, v in series.items() if v is not None]
        if not usable_years:
            continue
        year = max(usable_years)
        qty_series = (qty or {}).get(iso3, {})
        rows.append(
            {
                "hs6": hs6,
                "importer_iso3": iso3.upper(),
                "year": year,
                "import_usd": series[year],
                "import_qty": qty_series.get(year),
                "yoy_growth": compute_yoy(series),
                "cagr_3y": compute_cagr_3y(series),
                "is_transit_hub": is_transit_hub(iso3),
                "is_mirror": iso3.upper() in mirror,
                "source": source,
                "fetched_at": fetched_at,
            }
        )
    return rows


def run(hs6: str | None = None, years: Sequence[int] | None = None) -> int:
    """Refresh ``world_trade`` for the given HS6 codes / years (live bulk sync).

    Downloads bulk import flows from UN Comtrade (pandas + comtradeapicall — I7,
    here only), builds rows via :func:`build_rows`, and upserts ``world_trade``.
    Returns the number of rows written. The download + DB upsert are the Phase-3
    live piece; the transform (build_rows) is implemented and tested today.
    """
    # Lazy heavy imports — sanctioned here only (I7).
    #   import pandas as pd
    #   import comtradeapicall
    raise NotImplementedError(
        "world_trade_sync.run() goes live in Phase 3 (Comtrade key + DB upsert). "
        "The transform (build_rows/compute_yoy/compute_cagr_3y) is live now. See "
        "etl/README.md."
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Refresh the world_trade table (Stage 1).")
    p.add_argument("--hs6", help="HS6 code to refresh; omit for the full scope.")
    p.add_argument("--years", nargs="*", type=int, help="Data years to pull.")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    return run(hs6=args.hs6, years=args.years)


if __name__ == "__main__":
    raise SystemExit(main())

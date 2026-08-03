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


def run(hs6: str | None = None, years: Sequence[int] | None = None) -> int:
    """Refresh ``world_trade`` for the given HS6 codes / years.

    Returns the number of rows written. Not implemented in Phase 0.
    """
    # Lazy heavy imports — sanctioned here only (I7).
    #   import pandas as pd
    #   import comtradeapicall
    raise NotImplementedError(
        "world_trade_sync.run() lands in Phase 2 (table + Stage-1 query) and "
        "goes live in Phase 3 (Comtrade key). See etl/README.md."
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

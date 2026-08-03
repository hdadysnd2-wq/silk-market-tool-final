"""Refresh the official HS6 reference used by the classifier's confirm step.

The engine's HS classifier (``silk_hs_resolver``) matches product names against a
curated seed (``data/hs_codes.csv``); the human-confirm step
(``silk_hs_confirm``) cross-checks candidates against the full official HS6
reference (``data/hs_reference.csv``, ~5.6k rows). This job refreshes that
reference from UN Comtrade's HS classification bulk endpoint.

pandas + comtradeapicall live HERE ONLY (I7); imported lazily inside ``run()``.

Phase 0: documented skeleton. Wired for real in Phase 3 alongside the first live
Comtrade sync. Refreshing the reference NEVER auto-commits an HS code — human
confirmation (invariant I2) is unaffected; this only widens the candidate pool.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def run(dest: str = "data/hs_reference.csv") -> int:
    """Rebuild the HS6 reference. Returns rows written. Not implemented in Phase 0."""
    # Lazy heavy imports — sanctioned here only (I7).
    #   import pandas as pd
    #   import comtradeapicall
    raise NotImplementedError(
        "hs_reference_sync.run() lands in Phase 3 (live Comtrade). See etl/README.md."
    )


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Refresh the official HS6 reference.")
    p.add_argument("--dest", default="data/hs_reference.csv")
    args = p.parse_args(argv)
    return run(dest=args.dest)


if __name__ == "__main__":
    raise SystemExit(main())

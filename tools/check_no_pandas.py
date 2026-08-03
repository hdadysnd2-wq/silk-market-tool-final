#!/usr/bin/env python3
"""CI guard for invariant I7: pandas is confined to ``etl/``.

pandas is a heavyweight columnar library appropriate for offline bulk ETL, but
it must never appear in the hot request path or the intelligence engine. This
guard fails the build if any first-party *source* module under ``apps/`` or
``packages/silk_intel/silk_intel/`` imports pandas.

Scope decisions (deliberate, documented):

* ``etl/`` is the ONLY sanctioned home for pandas — it is not scanned.
* Test trees are excluded. The vendored engine's Google-Trends tests construct
  mock ``pandas.DataFrame`` fixtures because the runtime dependency ``pytrends``
  returns DataFrames; pandas thus arrives transitively but is used only in test
  fixtures, never in engine code. Excluding tests lets us keep the 2,500+
  vendored tests byte-identical (a merge invariant) while still enforcing I7
  where it matters — the library and application code.
* Virtualenvs, build caches and node_modules are excluded.

Run from the repo root:  ``python tools/check_no_pandas.py``
"""

from __future__ import annotations

import ast
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Directories whose *.py source is subject to the no-pandas rule.
SCAN_ROOTS = [
    REPO_ROOT / "apps",
    REPO_ROOT / "packages" / "silk_intel" / "silk_intel",
    REPO_ROOT / "packages" / "contracts",
]

# Path segments that exclude a file from scanning.
EXCLUDE_SEGMENTS = {
    "tests",
    ".venv",
    "venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "alembic",  # generated migration versions; not hot-path engine code
}


def _excluded(path: pathlib.Path) -> bool:
    return any(seg in EXCLUDE_SEGMENTS for seg in path.parts)


def _imports_pandas(path: pathlib.Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        # A file we cannot parse cannot be proven to import pandas; a real
        # syntax error will be caught by the test/lint jobs, not here.
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "pandas" or alias.name.startswith("pandas.")
                   for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "pandas" or (node.module or "").startswith("pandas."):
                return True
    return False


def main() -> int:
    offenders: list[pathlib.Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if _excluded(path):
                continue
            if _imports_pandas(path):
                offenders.append(path)

    if offenders:
        sys.stderr.write(
            "\nI7 VIOLATION — pandas imported outside etl/ (hot path / engine):\n"
        )
        for p in sorted(offenders):
            sys.stderr.write(f"  - {p.relative_to(REPO_ROOT)}\n")
        sys.stderr.write(
            "\npandas belongs in etl/ only. Use the engine's provenance-carrying "
            "data layer (silk_data_layer) in the request path instead.\n"
        )
        return 1

    print("I7 OK — no pandas imports under apps/ or packages/silk_intel (engine).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

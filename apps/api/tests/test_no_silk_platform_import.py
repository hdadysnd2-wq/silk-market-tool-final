"""Structural lock: the product NEVER wires the vendored ``silk_platform``.

``packages/silk_intel/silk_intel/silk_platform/`` is the engine's legacy
standalone console. It carries its own cold-send queue with NO per-email human
approval gate — the one in-repo send path outside the I3 state machine. It is
acceptable only while unreachable from the deployed product; this test makes
that unreachability a hard invariant instead of an accident (see ADR-0004).
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def test_apps_never_import_silk_platform():
    offenders = []
    for path in APP_ROOT.rglob("*.py"):
        for mod in _imported_modules(path):
            if mod == "silk_platform" or mod.startswith("silk_platform."):
                offenders.append(f"{path}: {mod}")
    assert offenders == [], (
        "silk_platform (unapproved legacy send pipeline) must never be wired "
        f"into the product: {offenders}"
    )

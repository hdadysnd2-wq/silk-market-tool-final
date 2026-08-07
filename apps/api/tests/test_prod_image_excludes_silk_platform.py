"""Regression locks: silk_platform stays out of the production image (Wave 2 item 5).

The legacy silk_platform product carries a cold-send queue with no per-email
approval gate (ADR-0004). Until now it shipped inside the api image because the
Dockerfile copies packages/ wholesale — the only barrier was the AST guard over
apps/api/app (test_no_silk_platform_import). Exclusion is now build-level:
.dockerignore drops the tree from the build context and the Dockerfile fails
the build if it reappears. These tests prove the exclusion is safe (the runtime
import graph never needs the tree) and pin both build guards.
"""

from __future__ import annotations

import importlib.abc
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


class _RaiseOnSilkPlatform(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002
        if fullname == "silk_platform" or fullname.startswith("silk_platform."):
            raise AssertionError(f"runtime import graph reached {fullname}")
        return None


def test_runtime_import_graph_never_needs_silk_platform():
    guard = _RaiseOnSilkPlatform()
    sys.meta_path.insert(0, guard)
    try:
        # The three entrypoints the image actually runs (api / worker / beat)
        # plus the engine-touching seams. Already-imported modules are proven by
        # the sys.modules sweep below; fresh imports are caught by the guard.
        import app.main  # noqa: F401
        import app.services.buyer_discovery  # noqa: F401
        import app.services.engine  # noqa: F401
        import app.services.report_view  # noqa: F401
        import app.workers.celery_app  # noqa: F401
        import app.workers.tasks  # noqa: F401
    finally:
        sys.meta_path.remove(guard)

    leaked = [m for m in sys.modules if m == "silk_platform" or m.startswith("silk_platform.")]
    assert leaked == [], f"silk_platform modules loaded at runtime: {leaked}"


def test_dockerignore_excludes_silk_platform():
    content = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "packages/silk_intel/silk_intel/silk_platform" in content.splitlines()


def test_dockerfile_fails_build_if_silk_platform_reappears():
    content = (REPO_ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    assert "test ! -e /app/packages/silk_intel/silk_intel/silk_platform" in content

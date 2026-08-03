"""Root conftest for the vendored Silk intelligence engine.

Repo A (Silk-market-intelligence) is a flat-module engine: its modules import
one another as top-level names (``import silk_data_layer``) and a handful of
them open reference data (``data/*.csv``) relative to the current working
directory (notably ``silk_hs_confirm``). Upstream this "just works" because the
suite runs from the repo root with the modules and ``data/`` side by side.

Vendoring the engine under ``packages/silk_intel/silk_intel/`` while keeping the
tests one level up (``packages/silk_intel/tests/``, byte-identical to Repo A)
means pytest may be launched from anywhere. This conftest makes resolution
robust regardless of the launch directory, WITHOUT editing a single vendored
test or module:

* the engine source dir is put on ``sys.path`` so ``import silk_*`` resolves;
* the process chdirs into that dir so cwd-relative ``data/*.csv`` opens resolve.

Both operations are idempotent and use absolute paths, so re-running or nesting
invocations is safe.
"""

import os
import sys

_PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_PKG_ROOT, "silk_intel")

if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# A few engine modules resolve reference data relative to cwd; anchor cwd to the
# engine source dir where ``data/`` lives so those opens succeed.
os.chdir(_SRC)

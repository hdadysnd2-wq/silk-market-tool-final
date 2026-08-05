"""Make the ``contracts`` package importable when running ``pytest tests``.

The package is pure-Python with no install step in CI (mirrors the etl lane), so
add its root to ``sys.path`` the same way the engine/api suites do.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

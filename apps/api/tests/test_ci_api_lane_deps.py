"""Guard: the CI ``api`` lane must re-run on its in-process dependencies.

apps/api has editable path-deps on packages/silk_intel and packages/contracts
and imports engine modules in-process (locked decision #2). If the CI ``api``
filter watches only apps/api, a PR changing the engine or contracts runs neither
the API suite (skipped) — so the integration seam breaks only after merge, on
main. This locks the filter so that regression can't silently return.
"""

from __future__ import annotations

from pathlib import Path

_CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def _api_filter_block() -> str:
    text = _CI.read_text()
    assert "api:" in text, "ci.yml has no `api` paths-filter"
    # Slice from the `api:` filter key to the next filter key (`web:`).
    start = text.index("            api:")
    end = text.index("            web:", start)
    return text[start:end]


def test_api_lane_watches_engine_and_contracts():
    block = _api_filter_block()
    assert '"packages/silk_intel/**"' in block
    assert '"packages/contracts/**"' in block
    assert '"apps/api/**"' in block

"""Deploy-config lock tests (audit 2026-08-07, suggested harness investment #1).

The 08-06 and 08-07 audits both found launch-breaking regressions that lived in
the DEPLOY SCRIPTS, not the code: ``STORAGE_BACKEND=local`` on a multi-container
topology (vision silently degraded, report downloads 404) and a hard
``COMTRADE_OFFLINE=1`` that permanently disabled the world screen. Code-level
guards (``REQUIRE_OBJECT_STORAGE``, fail-closed sync) exist but only fire when
the deploy scripts actually set the right variables — so the scripts themselves
are locked here, in the same spirit as ``test_no_mock_send_in_prod.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SH = (REPO_ROOT / "deploy-to-railway.sh").read_text()
PS1 = (REPO_ROOT / "deploy-to-railway.ps1").read_text()


def _default_path_lines(text: str) -> list[str]:
    """Lines that are active outside the explicit ALLOW_LOCAL_STORAGE opt-in."""
    return [
        line
        for line in text.splitlines()
        if not line.strip().startswith("#") and "ALLOW_LOCAL_STORAGE" not in line
    ]


def test_sh_default_path_never_ships_local_storage():
    # STORAGE_BACKEND=local may appear only inside the explicit
    # ALLOW_LOCAL_STORAGE=1 opt-in branch (its warn lines mention the variable's
    # consequences; the assignment itself sits on the guarded branch).
    guarded = re.findall(r"ALLOW_LOCAL_STORAGE.*?\belse\b", SH, flags=re.S)
    assert guarded, "the ALLOW_LOCAL_STORAGE opt-in branch must exist"
    outside = SH.replace(guarded[0], "")
    assert "STORAGE_BACKEND=local" not in [line.strip() for line in _default_path_lines(outside)], (
        "the default deploy path must not emit STORAGE_BACKEND=local (C2)"
    )


def test_sh_requires_object_storage_and_fails_closed():
    assert "REQUIRE_OBJECT_STORAGE=1" in SH, "S3 mode must fail loudly on drift (C2)"
    # The four S3 credentials must be required (bash `:?` fail-closed expansion).
    for var in ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        assert f"${{{var}:?" in SH, f"{var} must be required fail-closed (C2)"


def test_sh_does_not_hard_disable_comtrade():
    for line in _default_path_lines(SH):
        assert line.strip() != "COMTRADE_OFFLINE=1", (
            "the deploy script must not hard-disable the world-trade sync (C1)"
        )
    assert "COMTRADE_API_KEY=" in SH, "the Comtrade key must be plumbed through (C1)"


def test_sh_keeps_proxy_count_and_sentry():
    assert "TRUSTED_PROXY_COUNT=1" in SH, "login throttle must key on the real client IP"
    assert "SENTRY_DSN=" in SH, "error reporting must be plumbed through (H4)"


def test_sh_pins_engine_spend_cap_to_a_persistent_volume():
    # Otherwise the daily paid-call cap resets to zero on every redeploy.
    assert "SILK_DATA_DIR=/app/data" in SH
    assert "SILK_REQUIRE_PERSISTENT_DATA_DIR=1" in SH


def test_ps1_matches_sh_policy():
    assert "REQUIRE_OBJECT_STORAGE=1" in PS1
    assert "ALLOW_LOCAL_STORAGE" in PS1
    for line in _default_path_lines(PS1):
        assert "COMTRADE_OFFLINE=1" not in line, (
            "the PowerShell deploy script must not hard-disable the sync (C1)"
        )
    assert "TRUSTED_PROXY_COUNT=1" in PS1
    assert "SILK_DATA_DIR=/app/data" in PS1
    assert "SILK_REQUIRE_PERSISTENT_DATA_DIR=1" in PS1

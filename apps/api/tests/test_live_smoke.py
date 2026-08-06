"""The live-smoke harness is a safe no-op without keys.

With no vendor keys configured (the CI/offline default) every provider check must
report SKIP and the exit code must be 0 — so the script is safe to run anywhere
and never makes a live call or a send by accident. The per-provider live calls
themselves only run when a key is set and are not exercised here.
"""

from __future__ import annotations

from app import live_smoke
from app.config import get_settings


def test_all_checks_skip_without_keys():
    results = live_smoke.run_checks(get_settings())
    assert results, "checks ran"
    assert all(r.status == live_smoke.SKIP for r in results), [
        (r.slot, r.status, r.detail) for r in results
    ]
    # Every result is well-formed (a slot label and a reason).
    for r in results:
        assert r.slot and r.detail


def test_main_exits_zero_offline(capsys):
    assert live_smoke.main([]) == 0
    out = capsys.readouterr().out
    assert "skipped" in out


def test_localprice_check_present_and_skips_without_key():
    # The observed-price live path (audit blocker #6) is covered by the harness.
    settings = get_settings().model_copy(update={"localprice_api_key": ""})
    result = live_smoke._check_localprice(settings)
    assert result.status == live_smoke.SKIP
    assert "LOCALPRICE_API_KEY" in result.detail


def test_live_smoke_workflow_is_wired_with_exact_secret_names():
    # The audit's finding: the harness was wired to NO workflow. Lock the
    # workflow_dispatch lane and its exact env-var names (they must match the
    # settings the code reads, or the secrets never reach a live check).
    from pathlib import Path

    wf = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "live-smoke.yml"
    text = wf.read_text()
    assert "workflow_dispatch:" in text
    for var in (
        "ANTHROPIC_API_KEY",
        "COMTRADE_API_KEY",
        "LOCALPRICE_API_KEY",
        "SMARTLEAD_API_KEY",
        "GOOGLE_OAUTH_CLIENT_ID",
        "MICROSOFT_OAUTH_CLIENT_ID",
    ):
        assert f"{var}: ${{{{ secrets.{var} }}}}" in text, var


def test_smartlead_send_is_never_smoke_tested():
    # The sending path must never be auto-exercised (a real cold email). Even with
    # a key present AND the sequence verified it stays SKIP with a manual-pilot note.
    settings = get_settings().model_copy(
        update={"smartlead_api_key": "x", "smartlead_sequence_verified": True}
    )
    result = live_smoke._check_smartlead(settings)
    assert result.status == live_smoke.SKIP
    assert "NOT smoke-tested" in result.detail


def test_smartlead_reports_the_gated_state_with_its_unblock_step():
    # Key set but sequence unverified: the slot is fail-closed, and the smoke
    # report says so plus names the env var that unblocks it.
    settings = get_settings().model_copy(update={"smartlead_api_key": "x"})
    result = live_smoke._check_smartlead(settings)
    assert result.status == live_smoke.SKIP
    assert "GATED" in result.detail
    assert "SMARTLEAD_SEQUENCE_VERIFIED" in result.detail

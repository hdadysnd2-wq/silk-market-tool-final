"""Regression locks: the live brain-path smoke lane (Wave 3 item 9).

One real product through HS → screening → top-5 → buyers → executive report,
with real keys, in the workflow_dispatch live-smoke lane. Fail-closed keyless
(SKIP + exit 0, zero network) like every other live check; never sends email.
"""

from __future__ import annotations

from pathlib import Path

from app import live_smoke_brain

REPO = Path(__file__).resolve().parents[3]


def test_keyless_run_skips_cleanly_with_no_network(monkeypatch, capsys):
    # The suite runs keyless: run() must SKIP and exit 0 before touching the DB
    # or any socket.
    monkeypatch.setattr(
        "app.db.SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("DB must not be touched keyless")),
    )
    assert live_smoke_brain.run("/tmp/never-written.docx") == 0
    out = capsys.readouterr().out
    assert "SKIP" in out and "ANTHROPIC_API_KEY" in out


def test_brain_path_job_is_wired_in_the_workflow():
    wf = (REPO / ".github" / "workflows" / "live-smoke.yml").read_text(encoding="utf-8")
    assert "brain-path:" in wf
    assert "app.live_smoke_brain" in wf
    assert "pgvector/pgvector:pg16" in wf
    # The rendered executive report is the run's artifact.
    assert "executive_smoke.docx" in wf
    assert "upload-artifact" in wf
    # Paid spend is capped for the whole run.
    assert "SILK_PAID_DAILY_CAP" in wf


def test_brain_path_never_touches_the_send_path():
    src = (REPO / "apps" / "api" / "app" / "live_smoke_brain.py").read_text(encoding="utf-8")
    for forbidden in ("send_email", "smartlead", "MailboxProvider", "send_approved"):
        assert forbidden not in src, forbidden


def test_simulated_confirmation_is_loudly_labeled():
    src = (REPO / "apps" / "api" / "app" / "live_smoke_brain.py").read_text(encoding="utf-8")
    assert "hs_confirm(simulated)" in src  # the I2 simulation is never silent

"""Invariant I5 — paid engine agents run only inside a re-established /deepen scope.

The engine gates its paid agents (LocalPrice, Volza, Explee) with a
``contextvars`` flag set only inside ``silk_context.deepen_context()``.
``contextvars`` do not cross the process boundary from the API into a Celery
worker, so the deepen intent is carried explicitly in the task payload and
re-established in the worker via ``app.services.engine.deepen_scope``.

These tests prove the structural guard end to end:

* a paid agent invoked outside deepen returns a *skipped* report — flagged failed,
  note tagged, value ``None`` (no fabrication, I1), and crucially **no call is
  attempted** (``_execute`` never runs);
* the same agent runs normally inside ``deepen_scope(True)``;
* ``deepen_scope(False)`` keeps the guard closed;
* the scope resets cleanly on exit (no leakage into later work).

They need no database, so they exercise pure engine + adapter behaviour.
"""

from __future__ import annotations

import silk_context
from silk_agents import AgentReport, BaseAgent
from silk_data_layer import DataPoint

from app.services import engine


class _SpyPaidAgent(BaseAgent):
    """A paid agent whose ``_execute`` records whether the guard let it run.

    ``_execute`` must never be reached outside deepen — reaching it would mean a
    paid call was attempted, which is exactly what I5 forbids.
    """

    PAID = True

    def __init__(self) -> None:
        super().__init__("SpyPaidAgent")
        self.executed = False

    def _execute(self, task: dict) -> AgentReport:
        self.executed = True
        return AgentReport(
            self.name,
            [DataPoint("PROOF", self.name, 1.0, "executed inside deepen")],
            False,
            "ran",
        )


def test_paid_agent_skipped_outside_deepen():
    agent = _SpyPaidAgent()
    report = agent.run({})

    assert agent.executed is False, "paid agent must not attempt any call outside deepen"
    assert report.failed is True
    assert "paid agent outside /deepen" in report.summary
    # I1: the skipped report declares a gap, never a fabricated value.
    assert report.findings[0].value is None
    assert report.findings[0].confidence == 0.0


def test_paid_agent_runs_inside_reestablished_deepen_scope():
    agent = _SpyPaidAgent()
    with engine.deepen_scope(True):
        report = agent.run({})

    assert agent.executed is True
    assert report.failed is False
    assert report.findings[0].value == "PROOF"


def test_deepen_scope_false_keeps_guard_closed():
    agent = _SpyPaidAgent()
    with engine.deepen_scope(False):
        report = agent.run({})

    assert agent.executed is False
    assert "paid agent outside /deepen" in report.summary


def test_deepen_scope_activates_and_resets_contextvar():
    assert silk_context.deepen_active() is False
    with engine.deepen_scope(True):
        assert silk_context.deepen_active() is True
    # The contextvar is reset on exit — no leakage into subsequent free-path work.
    assert silk_context.deepen_active() is False


def test_classify_task_carries_deepen_and_returns_provenance():
    """The Celery task wires the engine and returns provenance-tagged proposals."""
    from app.workers.tasks import classify_product_hs

    result = classify_product_hs("honey")
    assert result["deepen"] is False
    assert result["proposals"], "expected at least one HS proposal for a known product"
    top = result["proposals"][0]
    # Every proposal carries the unified envelope (decision #4 / I1).
    assert top["provider"] == "silk_hs_resolver"
    assert "confidence" in top and "is_missing" in top and "note" in top

"""Invariant I5 under Celery *eager* mode — the async tasks re-establish /deepen.

Under ``CELERY_TASK_ALWAYS_EAGER`` (set by the test conftest) ``.delay()`` runs a
task inline in the calling process. Eager mode must NOT become a hole in invariant
I5: each pipeline task still has to re-establish the engine's ``/deepen`` scope
from the explicit ``deepen`` payload flag, because ``contextvars`` do not cross the
process boundary and the API never activates deepen in the worker's stead.

These tests run the *new* async tasks eagerly and prove the guard end to end:

* the ``deepen`` observed by ``engine.deepen_active()`` *inside* the eagerly-run
  task equals the payload flag — and crucially, since the test process has no
  ambient deepen, a ``True`` observation can ONLY come from the task itself calling
  ``engine.deepen_scope(True)`` (i.e. eager mode did not skip it);
* a paid engine agent invoked inside the task runs iff ``deepen`` — outside it is
  structurally skipped (flagged failed, ``value=None``, no call attempted, I1),
  reusing the exact hook from ``test_deepen_guard``;
* the scope resets on task exit (no leakage into later free-path work).
"""

from __future__ import annotations

import pytest
from silk_agents import AgentReport, BaseAgent
from silk_data_layer import DataPoint

from app.services import engine
from app.workers import tasks


class _SpyPaidAgent(BaseAgent):
    """A paid agent whose ``_execute`` records whether the guard let it run.

    Reaching ``_execute`` outside deepen would mean a paid call was attempted —
    exactly what I5 forbids. Mirrors ``tests.test_deepen_guard._SpyPaidAgent``.
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


def _assert_guard(observed: dict, agent: _SpyPaidAgent, deepen: bool) -> None:
    # The scope the task saw INSIDE its body equals the payload flag. With no
    # ambient deepen in this process, a True here proves the task re-established
    # engine.deepen_scope from the payload — eager mode did not skip it.
    assert observed["deepen_active"] is deepen
    assert agent.executed is deepen
    report = observed["report"]
    if deepen:
        assert report.failed is False
        assert report.findings[0].value == "PROOF"
    else:
        assert report.failed is True
        assert "paid agent outside /deepen" in report.summary
        # I1: the skipped report declares a gap, never a fabricated value.
        assert report.findings[0].value is None


@pytest.mark.parametrize("deepen", [False, True])
def test_intake_task_reestablishes_deepen_under_eager(db, factory, monkeypatch, deepen):
    from app.models import Product

    product = Product(
        factory_id=factory.id, name_ar="عسل السدر", name_en="Sidr Honey", currency="USD"
    )
    db.add(product)
    db.commit()

    agent = _SpyPaidAgent()
    observed: dict = {}

    def _spy_describe(db_, product_, llm_):
        # Runs INSIDE the task's `with engine.deepen_scope(deepen):` block.
        observed["deepen_active"] = engine.deepen_active()
        observed["report"] = agent.run({})
        return {}

    monkeypatch.setattr("app.services.product_vision.describe_product", _spy_describe)

    # No ambient deepen in the test process — so any deepen seen inside the task is
    # the task's own re-established scope, not a leaked/inherited one.
    assert engine.deepen_active() is False

    result = tasks.process_product_intake.delay(str(product.id), deepen=deepen)
    assert result.successful()  # eager + eager_propagates: a raise would surface here

    _assert_guard(observed, agent, deepen)
    # The scope resets on task exit — no leakage into subsequent free-path work.
    assert engine.deepen_active() is False


@pytest.mark.parametrize("deepen", [False, True])
def test_stage2_task_reestablishes_deepen_under_eager(db, monkeypatch, deepen):
    from app.models import Analysis

    analysis = Analysis(product_id=None, product_name="Sidr Honey", status="ranked")
    db.add(analysis)
    db.commit()

    agent = _SpyPaidAgent()
    observed: dict = {}

    def _spy_enrich(db_, analysis_, hs6_):
        # Runs INSIDE the task's `with engine.deepen_scope(deepen), budget_scope():`.
        observed["deepen_active"] = engine.deepen_active()
        observed["report"] = agent.run({})
        return []

    monkeypatch.setattr("app.services.stage2.enrich_shortlist", _spy_enrich)

    assert engine.deepen_active() is False

    result = tasks.run_stage2_enrich.delay(str(analysis.id), "040900", deepen=deepen)
    assert result.successful()

    _assert_guard(observed, agent, deepen)
    assert engine.deepen_active() is False

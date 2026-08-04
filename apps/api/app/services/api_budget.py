"""Per-analysis external-API call budget (locked decision #5 / funnel Stages 2-3).

The master prompt caps live Comtrade usage at **≤150 calls per analysis** and
asks that API spend be logged per analysis. Live external calls charge against an
active budget scope; once the ceiling is reached, further calls are *refused* so
the caller degrades (falls back to cache/fixtures — never fabricates, I1) instead
of running the key budget dry mid-analysis.

The budget lives in a ``contextvar`` so it is ambient for the duration of one
analysis without threading a counter through every call. Exactly like the
``/deepen`` guard (I5), a contextvar does **not** cross a process boundary — each
Celery task that can trigger live fetches establishes its own scope, so the
budget is re-established inside the worker.

With **no active scope** ``charge()`` returns ``True`` (unmetered), so offline /
mocked / ad-hoc paths are unaffected — only work wrapped in ``budget_scope`` is
metered and capped.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.logging import get_logger

log = get_logger(__name__)

# Master-prompt ceiling: ≤150 live Comtrade calls per analysis.
DEFAULT_ANALYSIS_BUDGET = 150


@dataclass
class ApiBudget:
    """A live-call allowance for one analysis, with per-source spend tracking."""

    limit: int
    spent_by_source: dict[str, int] = field(default_factory=dict)

    @property
    def spent(self) -> int:
        return sum(self.spent_by_source.values())

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)


_current: contextvars.ContextVar[ApiBudget | None] = contextvars.ContextVar(
    "api_budget", default=None
)


def current_budget() -> ApiBudget | None:
    """The budget active in this context, or ``None`` when unmetered."""
    return _current.get()


def charge(n: int = 1, *, source: str = "external") -> bool:
    """Charge ``n`` live calls against the active budget.

    Returns ``True`` if the calls are within budget (or there is no active
    budget), ``False`` if they would exceed the ceiling — in which case *nothing*
    is charged and the caller must degrade rather than make the call.
    """
    budget = _current.get()
    if budget is None:
        return True  # unmetered outside an analysis scope
    if budget.spent + n > budget.limit:
        return False
    budget.spent_by_source[source] = budget.spent_by_source.get(source, 0) + n
    return True


@contextmanager
def budget_scope(limit: int = DEFAULT_ANALYSIS_BUDGET, *, label: str = "") -> Iterator[ApiBudget]:
    """Establish a live-call budget for the enclosed work and log spend on exit."""
    budget = ApiBudget(limit=limit)
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)
        log.info(
            "api_budget_spent",
            label=label,
            limit=budget.limit,
            spent=budget.spent,
            by_source=budget.spent_by_source,
        )

"""In-process adapter to the market-intelligence engine (``packages/silk_intel``).

The engine is imported directly (no HTTP hop — locked decision #2) and every
number it returns is wrapped in the platform-wide provenance envelope
(``contracts.DataContract`` — decision #4 / invariant I1): a failed resolve
carries ``value=None, confidence=0.0`` with a note, never a fabricated code.

Two responsibilities live here:

1. **HS resolution** — proposes an HS6 code (+ ranked alternatives) for a product
   name. This is a *proposal only*; the human-confirmation gate (invariant I2)
   is enforced upstream and is never bypassed by this adapter.
2. **The /deepen scope port (invariant I5).** The engine gates its paid agents
   with a ``contextvars`` flag set only inside ``silk_context.deepen_context()``.
   ``contextvars`` do NOT cross the process boundary from the API into a Celery
   worker, so the deepen intent must be carried explicitly in the task payload
   and re-established inside the worker via :func:`deepen_scope`. Outside that
   scope a paid engine agent returns a skipped report *without attempting any
   call*, even with keys present.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from contracts import DataContract, from_datapoint

# Provider tag stamped onto every envelope produced by the engine's name-based
# HS classifier, so provenance survives all the way to the database.
_HS_PROVIDER = "silk_hs_resolver"


def resolve_hs(product_name: str) -> DataContract:
    """Best HS6 proposal for a product name, as a provenance envelope.

    Delegates to the engine's single classifier (``silk_hs_resolver``) — Repo B
    keeps no parallel HS logic (one classifier only). A weak/no match returns a
    ``DataContract`` with ``value=None`` and ``confidence=0.0`` (I1), never a
    guessed code.
    """
    import silk_hs_resolver

    return from_datapoint(silk_hs_resolver.resolve(product_name), provider=_HS_PROVIDER)


def resolve_hs_candidates(product_name: str, top_n: int = 3) -> list[DataContract]:
    """Ranked HS6 candidates for the human-confirmation screen (I2).

    Returns up to ``top_n`` envelopes ordered by confidence. The confirm UI shows
    these with their confidence so a human can pick — this adapter never
    auto-commits a code.
    """
    import silk_hs_resolver

    return [
        from_datapoint(dp, provider=_HS_PROVIDER)
        for dp in silk_hs_resolver.resolve_all(product_name, top_n=top_n)
    ]


@contextlib.contextmanager
def deepen_scope(deepen: bool) -> Iterator[None]:
    """Re-establish the engine's ``/deepen`` context inside a worker (I5).

    Pass the deepen flag from the Celery task payload. When ``True`` the paid
    engine agents (LocalPrice, Volza, Explee) are permitted to run *for the
    duration of this block only*; when ``False`` (the default for the free
    ``/analyze`` path) they structurally return a skipped report with no call
    attempted. The flag must be carried explicitly in the payload because
    ``contextvars`` set in the API process are not visible in the worker process.
    """
    import silk_context

    if deepen:
        with silk_context.deepen_context():
            yield
    else:
        yield


def deepen_active() -> bool:
    """Whether a paid-layer (deepen) scope is currently active in this process."""
    import silk_context

    return silk_context.deepen_active()

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


def hs_ai_allowed() -> bool:
    """Whether the engine's Claude HS classifier may be invoked.

    Mirrors the engine's own ``/analyze`` predicate: an Anthropic key must be
    configured. Spend gating (``silk_usage`` daily cap + USD reservation) and
    result caching live INSIDE ``classify_general`` — no reservation logic
    belongs on the product side. Keyless the classifier still runs
    deterministically and returns ``tier="manual"`` (a declared gap, I1),
    never a mock.
    """
    from app.config import get_settings

    return bool(get_settings().anthropic_api_key)


def hs_ai_needed(product_name: str) -> bool:
    """Cheap, network-free check: would the deterministic path suffice?

    Delegates to the engine's ``needs_classifier`` so no paid reservation is
    ever consumed for a product the offline resolver already handles.
    """
    import silk_hs_classifier

    return silk_hs_classifier.needs_classifier(product_name)


def classify_hs_general(
    product_name: str,
    *,
    ingredients: list[str] | None = None,
    category: str | None = None,
) -> dict:
    """LLM-backed HS classification over the FULL WCO nomenclature (symptom A fix).

    Delegates to the engine's ``silk_hs_classifier.classify_general`` — Claude
    proposes, then a deterministic no-fabrication gate validates every candidate
    (structural chapter check + term-overlap measurement), spend is reserved
    atomically against ``SILK_PAID_DAILY_CAP`` inside the engine, and repeat
    products are served from the engine's result cache. Returns the engine's
    dict verbatim: ``{tier: "auto"|"candidates"|"manual", hs6, confidence,
    candidates: [{hs6, description_ar, band_ar, reason_ar, verified, ...}],
    message, source, used_llm}``. ``tier="manual"`` is the honest keyless /
    can't-decide outcome — the caller must treat it as a declared gap, never
    surface its raw suggestion rows as proposals.
    """
    import silk_hs_classifier

    return silk_hs_classifier.classify_general(
        product_name,
        ingredients=ingredients,
        category=category,
        allow_claude=hs_ai_allowed(),
    )


def stage1_screen_score(
    import_usd: float | None,
    cagr_3y: float | None = None,
    yoy_growth: float | None = None,
) -> float:
    """Stage-1 world-funnel screening score via the engine (zero network).

    Delegates to ``silk_market_ranker.stage1_screen_score`` — the engine owns the
    scoring model, so the platform never keeps a parallel one. Import volume is
    modulated by a bounded multi-year-trend factor (locked decision #8: the trend
    feeds the score); a missing volume is a declared gap (``0.0``), never a
    fabricated number (I1). The transit-port penalty (I9) is applied by the caller
    so the guard and its visible tag stay co-located in the funnel.
    """
    import silk_market_ranker

    return silk_market_ranker.stage1_screen_score(
        import_usd, cagr_3y=cagr_3y, yoy_growth=yoy_growth
    )


def score_market_components(rows: list[dict]) -> list[dict]:
    """Score markets with the engine's audited weighted model (Wave 3 item 2).

    ``rows``: ``[{"iso3": str, "components": {name: {"value", "source",
    "confidence", "note"}}}]`` where component names are the engine's four
    (``market_size``, ``saudi_position``, ``demand_capacity``, ``competition``).
    The platform supplies its OWN synced data; the engine owns the model —
    weights, per-cohort normalization, renormalization over present components,
    competition inversion, and the I9 transit-hub demotion. Returns
    ``[{"iso3", "total_score", "confidence", "transit_hub"}]`` aligned by
    index. A missing component is skipped and lowers confidence — never a
    fabricated value (I1).
    """
    import silk_market_ranker
    from silk_data_layer import DataPoint, _today

    engine_rows = [
        {
            "iso3": r["iso3"],
            "components": {
                name: DataPoint(
                    c.get("value"),
                    c.get("source", ""),
                    c.get("confidence", 0.0),
                    c.get("note", ""),
                    c.get("retrieved_at") or _today(),
                )
                for name, c in r["components"].items()
            },
        }
        for r in rows
    ]
    return silk_market_ranker.score_component_rows(engine_rows)


def hs6_reference(hs6: str) -> tuple[bool, str | None]:
    """Validate a manually entered HS6 against the engine's WCO reference.

    Returns ``(is_valid, official_description_or_None)``. ``is_valid`` is a purely
    structural check (six digits + a real WCO chapter that is not domain-excluded)
    delegated to the engine — so a genuine code missing from the platform's small
    seed catalogue is still accepted. The description, when present, is the
    official WCO reference text (real, sourced data — not fabricated, I1); it is
    ``None`` when the code is valid but outside the reference sample.
    """
    import silk_hs_resolver

    code = (hs6 or "").strip()
    if len(code) != 6 or not code.isdigit():
        return False, None
    if not silk_hs_resolver.chapter_valid(code):
        return False, None
    if silk_hs_resolver.exclusion_note(code) is not None:
        return False, None
    description = silk_hs_resolver.official_description(code) or None
    return True, description


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

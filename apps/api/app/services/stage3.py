"""Funnel Stage 3: FREE per-market deep-dive on the top-5 finalists (offline).

After Stage 1 (local screen) and Stage 2 (budgeted enrich → top 5), Stage 3 runs
a per-country deep-dive on the finalists using ONLY the engine's FREE, offline
capabilities (invariant I5 — the paid observed-prices/localprice/volza/explee
layers stay structurally out at ``deepen=False``):

  * competitors  — the competitor snapshot's top exporters (offline Comtrade),
  * requirements — the engine's ``RequirementsAgent`` checklist (offline L1 CSV),
  * threads      — the zero-network ``correlation.correlate`` threads.

Every value is real or a declared gap (I1): a finalist we hold no alpha-2 for is
skipped with a note (never a fabricated deep-dive), and the correlation engine
declares any missing signal rather than inventing it. The result persists on the
row's ``deepdive`` and the row is marked ``stage = 3``. The caller commits.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Analysis, CountryRanking, MarketSnapshot, Product
from app.providers.countries import iso3_to_iso2
from app.services import heartbeat
from app.services.competitor_snapshot import build_snapshot

log = get_logger(__name__)


def _requirements_rows(iso3: str, hs6: str) -> list[dict]:
    """FREE offline requirements/compliance checklist for one market (I1/I5).

    Instantiates the engine's ``RequirementsAgent`` and runs it fully offline. The
    task keys are ``market_iso3`` + ``hs_code`` — verified against
    ``silk_requirements_agent.RequirementsAgent._execute`` (``with_live_verification``
    is left off, so no network is touched). Each finding becomes a plain-JSON row
    carrying its value + provenance envelope; a ``None`` value with a note is a
    declared gap, never a fabricated requirement.
    """
    from silk_requirements_agent import RequirementsAgent

    report = RequirementsAgent().run({"market_iso3": iso3, "hs_code": hs6})
    return [
        {
            "value": f.value,  # dict {item, authority, direction, source_url, seq} or None (gap)
            "source": f.source,
            "confidence": float(f.confidence),
            "note": f.note,
        }
        for f in report.findings
    ]


def _correlation_threads(
    snapshot: MarketSnapshot, product: Product | None, product_name: str
) -> dict:
    """Zero-network correlation threads for one market (I1) — no external calls.

    Builds the in-memory ``row`` the engine's ``correlation.correlate`` expects:
    the snapshot's ``top_exporters`` map into ``row["competitors_named"]`` (each
    element ``{"value": {"title", "link"}}`` — the shape ``correlation._value``
    reads) so competitor threads populate. The ``product_card`` is built from the
    Product's REAL fields (``price_min`` → ``cost_per_unit``, ``currency``); fields
    the Product does not carry stay ``None`` (declared gaps). ``correlate`` returns
    the SINGULAR keys ``entry_thread`` / ``contacts_thread``; missing signals (no
    observed prices in the free sweep) are declared, never fabricated.
    """
    import correlation

    competitors_named = [
        {"value": {"title": ex.get("exporter_name") or ex.get("exporter_iso2"), "link": None}}
        for ex in (snapshot.top_exporters or [])
        if ex.get("exporter_name") or ex.get("exporter_iso2")
    ]
    row = {"competitors_named": competitors_named}
    product_card = {
        "cost_per_unit": (
            float(product.price_min) if product and product.price_min is not None else None
        ),
        "unit": None,
        "tier": None,
        "monthly_capacity": None,
        "shipping_per_unit": None,
        "currency": product.currency if product else None,
    }
    return correlation.correlate(row, product_card, product_name)


def deepdive_shortlist(
    db: Session, analysis: Analysis, hs6: str, product: Product | None
) -> list[CountryRanking]:
    """FREE per-market deep-dive on this analysis's Stage-2 top-5 finalists.

    Loads the finalists (``rank <= 5``) and, for each, runs the engine's free
    offline layers — competitor snapshot, requirements checklist, correlation
    threads — persisting the result on ``deepdive`` and marking the row
    ``stage = 3``. A finalist with no alpha-2 mapping is a declared gap on
    ``deepdive`` (I1), never fabricated; the paid layers stay structurally out
    (``deepen=False`` in the caller). ``db.flush()`` only — the caller commits.
    """
    finalists = list(
        db.scalars(
            select(CountryRanking)
            .where(CountryRanking.analysis_id == analysis.id, CountryRanking.rank <= 5)
            .order_by(CountryRanking.rank)
        )
    )
    deepened = 0
    for r in finalists:
        # Liveness beat per finalist — see services.heartbeat (symptom B).
        heartbeat.beat(analysis.id)
        iso2 = iso3_to_iso2(r.importer_iso3)
        if iso2 is None:
            # I1 — no alpha-2 to drive the deep-dive; declare the gap, never fabricate.
            r.deepdive = {"note": "no iso2 mapping", "importer_iso3": r.importer_iso3}
            continue
        snapshot = build_snapshot(db, hs6, iso2)
        r.deepdive = {
            "competitors": snapshot.top_exporters or [],
            "requirements": _requirements_rows(r.importer_iso3, hs6),
            "threads": _correlation_threads(snapshot, product, analysis.product_name),
        }
        r.stage = 3
        deepened += 1
    db.flush()
    log.info(
        "stage3_deepdived",
        analysis_id=str(analysis.id),
        hs6=hs6,
        deepened=deepened,
        finalists=len(finalists),
    )
    return finalists

"""Adapter: platform report data → the engine's unified view-model (``build_view``).

Locked decision #7: the full Word report derives from the engine's ONE template
(``silk_render.build_view`` → ``silk_reports.render_docx``), not a parallel
renderer. This reconstitutes an engine ``result`` from the platform's persisted
analysis — the world-funnel ``CountryRanking`` rows plus the per-market
``MarketSnapshot`` — so the Word export is the same sourced-per-figure,
"limits of this report" document the engine emits.

Every figure travels as the engine's ``DataPoint`` provenance envelope. A value
the platform genuinely cannot source (demand-capacity = income-PPP × population,
and the weighted verdict/score, which need Stage-2 enrichment / synthesis) is a
declared gap (``value=None``, confidence ``0.0``) — the report shows the gap
honestly, it is never fabricated (I1).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Analysis,
    Buyer,
    Contact,
    CountryRanking,
    Market,
    MarketSnapshot,
    Product,
    ProductBuyerMatch,
)
from app.providers.countries import iso3_to_iso2
from app.services.report import _hs_confidence

#: Top-N funnel markets carried into the full report (mirrors the funnel top-5).
TOP_MARKETS = 5

#: Cap on per-market executive rows (competitors, buyers) — the executive report
#: is a summary, not a dump.
EXEC_LIST_CAP = 5

#: Client-facing line shown INSTEAD of the generic empty-prices state when the
#: observed-price slot fails closed (``GatedPriceProvider``, audit C3): no price
#: source is configured at all, so the gap is "pending a data source" — not
#: "searched and nothing was observed". Bilingual: the docx derivative is
#: Arabic-first, the JSON payload is also read by English-speaking operators.
PRICING_PENDING_LINE = "الأسعار بانتظار مصدر بيانات — pricing pending data source"


def _price_source_pending() -> bool:
    """True when NO observed-price source is configured (the slot is gated).

    The registry returns the C3 ``GatedPriceProvider`` exactly when no
    ``LOCALPRICE_API_KEY`` is set outside ``local`` and there is no explicit
    ``ALLOW_MOCK_DATA`` demo opt-in. In that state the executive prices section
    must say it is *pending a data source* rather than render the generic
    "not observed" empty state (which implies a source was consulted).
    """
    from app.providers.registry import get_price_provider

    return getattr(get_price_provider(), "name", "") == "gated-prices"


def _dp(
    value: float | None,
    source: str,
    note: str = "",
    data_year: int | None = None,
    *,
    confidence: float | None = None,
    retrieved_at: str | None = None,
) -> dict:
    """Engine ``DataPoint``-shaped provenance dict.

    I1: a ``None`` value is a declared gap — confidence ``0.0`` and a
    ``no_record`` status, never a fabricated zero. A PRESENT value carries only
    the provenance the caller actually has: ``confidence`` stays ``None``
    ("not scored" — ``confidence_phrase`` renders it as such) unless a real
    upstream score exists; no number is ever synthesized here.
    """
    present = value is not None
    return {
        "value": value,
        "source": source,
        "confidence": confidence if present else 0.0,
        "note": note,
        "retrieved_at": retrieved_at if present else None,
        "status": "" if present else "no_record",
        "data_year": data_year,
    }


def _saudi_share(snapshot: MarketSnapshot | None) -> float | None:
    """Saudi supplier share (0..1) of this market, from the snapshot's exporters."""
    if snapshot is None or not snapshot.top_exporters:
        return None
    for exporter in snapshot.top_exporters:
        if (exporter.get("exporter_iso2") or "").upper() == "SA":
            share = exporter.get("share_pct")
            return float(share) / 100.0 if share is not None else None
    return None


def _top_supplier_share(snapshot: MarketSnapshot | None) -> float | None:
    """Concentration proxy: the largest single supplier's share (0..1)."""
    if snapshot is None or not snapshot.top_exporters:
        return None
    shares = [
        float(e["share_pct"]) / 100.0
        for e in snapshot.top_exporters
        if e.get("share_pct") is not None
    ]
    return max(shares) if shares else None


def _snapshot_for(db: Session, hs_code: str | None, iso2: str | None) -> MarketSnapshot | None:
    """The persisted ``MarketSnapshot`` for one (hs_code, market), if any."""
    if not hs_code or not iso2:
        return None
    return db.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.hs_code == hs_code,
            MarketSnapshot.market_iso2 == iso2,
        )
    )


def _market_row(db: Session, product: Product, ranking: CountryRanking) -> dict:
    iso3 = ranking.importer_iso3
    iso2 = iso3_to_iso2(iso3)
    market = db.get(Market, iso2) if iso2 else None
    snapshot = _snapshot_for(db, product.hs_code, iso2)

    # Real retrieval provenance, carried through instead of being discarded:
    # snapshot figures were fetched at snapshot.fetched_at; funnel-screen rows
    # were computed when the ranking row was written.
    snapshot_fetched = (
        snapshot.fetched_at.isoformat() if snapshot is not None and snapshot.fetched_at else None
    )
    ranking_written = (ranking.updated_at or ranking.created_at).isoformat()

    # market_size — prefer the snapshot's live total, else the funnel screen value.
    if snapshot is not None and snapshot.total_import_usd is not None:
        usd: float | None = float(snapshot.total_import_usd)
        size_source = "comtrade"
        size_retrieved = snapshot_fetched
    elif ranking.import_usd is not None:
        usd = float(ranking.import_usd)
        size_source = "world_trade"
        size_retrieved = ranking_written
    else:
        usd = None
        size_source = "world_trade"
        size_retrieved = None
    if usd is not None:
        note = f"total imports HS{product.hs_code} {ranking.year}"
        tags = [t for t in (ranking.tags or []) if t]
        if tags:  # transit-hub / mirror provenance stays visible on the figure (I9)
            note += " · " + ", ".join(tags)
    else:
        note = "no reported import data"

    saudi = _saudi_share(snapshot)
    concentration = _top_supplier_share(snapshot)

    return {
        "country": (market.name_en if market else None) or iso3,
        "iso3": iso3,
        # The weighted 0..1 score / confidence come from the engine's full ranker
        # (Stage-2/3); the funnel persists only rank + screen inputs, so here they
        # are declared absent rather than fabricated.
        "total_score": None,
        "confidence": None,
        "components": {
            "market_size": _dp(usd, size_source, note, ranking.year, retrieved_at=size_retrieved),
            "saudi_position": _dp(
                saudi,
                "comtrade",
                "Saudi supplier share of this market"
                if saudi is not None
                else "Saudi not among the reported top suppliers",
                ranking.year,
                retrieved_at=snapshot_fetched,
            ),
            "demand_capacity": _dp(
                None,
                "World Bank",
                "income (PPP) × population — Stage-2 enrichment, not in the local screen",
            ),
            "competition": _dp(
                concentration,
                "comtrade",
                "largest-supplier concentration"
                if concentration is not None
                else "no supplier shares reported",
                ranking.year,
                retrieved_at=snapshot_fetched,
            ),
        },
    }


def _latest_analysis(db: Session, product: Product) -> Analysis | None:
    """The product's most recent analysis run — the one the report reflects."""
    return db.scalar(
        select(Analysis)
        .where(Analysis.product_id == product.id)
        .order_by(Analysis.created_at.desc())
    )


def _analysis_rankings(db: Session, analysis: Analysis | None) -> list[CountryRanking]:
    """The persisted world-funnel rankings of an analysis, ordered by rank."""
    if analysis is None:
        return []
    return list(
        db.scalars(
            select(CountryRanking)
            .where(CountryRanking.analysis_id == analysis.id)
            .order_by(CountryRanking.rank)
        )
    )


def _engine_result(db: Session, product: Product, rankings: list[CountryRanking]) -> dict:
    """Assemble the engine ``result`` dict from already-loaded funnel rankings."""
    rows = [_market_row(db, product, r) for r in rankings[:TOP_MARKETS]]
    years = [r.year for r in rankings if r.year is not None]
    data_year = max(years) if years else None

    return {
        "classified": bool(product.hs_code),
        "product": product.name_en or product.name_ar or "",
        "hs_code": product.hs_code or "",
        "hs_confidence": _hs_confidence(product),
        "year": data_year,
        "data_year": data_year,
        "markets": rows,
    }


def build_engine_result(db: Session, product: Product) -> dict:
    """Reconstitute an engine ``result`` from the product's latest analysis.

    Feeds ``silk_render.build_view``. Markets come from the persisted world-funnel
    shortlist (top 5), each carrying sourced ``market_size`` / ``saudi_position`` /
    ``competition`` figures and a declared-gap ``demand_capacity`` (I1). With no
    analysis yet, ``markets`` is empty and ``build_view`` renders a valid stub.
    """
    analysis = _latest_analysis(db, product)
    return _engine_result(db, product, _analysis_rankings(db, analysis))


def _screening_summary(analysis: Analysis | None) -> dict:
    """Funnel-transparency header: how wide the screen was and where it stands.

    With no analysis yet every field is a declared absence (I1): ``total_screened``
    and ``analysis_at`` stay ``None`` and the status honestly reads ``"none"``.
    """
    if analysis is None:
        return {"total_screened": None, "analysis_status": "none", "analysis_at": None}
    at = analysis.updated_at or analysis.created_at
    return {
        "total_screened": analysis.total_screened,
        "analysis_status": analysis.status,
        "analysis_at": at.isoformat() if at else None,
    }


def _executive_buyers(db: Session, product: Product, iso2: str | None) -> list[dict]:
    """Top buyer matches for (product, market), each with its stored provenance.

    Ordered by relevance (name as a deterministic tiebreak), capped at
    ``EXEC_LIST_CAP``. ``contacts`` is the count of Contact rows discovered for
    the buyer — a real number from the database, never an estimate.
    """
    if not iso2:
        return []
    rows = db.execute(
        select(ProductBuyerMatch, Buyer, func.count(Contact.id))
        .join(Buyer, Buyer.id == ProductBuyerMatch.buyer_id)
        .outerjoin(Contact, Contact.buyer_id == Buyer.id)
        .where(
            ProductBuyerMatch.product_id == product.id,
            ProductBuyerMatch.market_iso2 == iso2,
        )
        .group_by(ProductBuyerMatch.id, Buyer.id)
        .order_by(ProductBuyerMatch.relevance_score.desc(), Buyer.name)
        .limit(EXEC_LIST_CAP)
    ).all()
    return [
        {
            "name": buyer.name,
            "source": buyer.source.value,
            "confidence": (
                float(buyer.source_confidence) if buyer.source_confidence is not None else None
            ),
            "relevance_score": match.relevance_score,
            "contacts": int(contact_count),
            "legal_review_required": buyer.legal_review_required,
            # Honest demonstration flag: a buyer surfaced by a mock/offline
            # adapter must never read as observed customs data in the client
            # report (audit C6, I1). The renderer marks these rows.
            "is_demo": _is_demo_provider(buyer.provider_name),
            "provider": buyer.provider_name,
        }
        for match, buyer, contact_count in rows
    ]


def _is_demo_provider(provider_name: str | None) -> bool:
    """True when a stored provenance name is a deterministic mock/fixture.

    ``sample`` covers the shipments stand-in (``customs_sample``, J4), whose
    fabricated importers additionally carry a "SAMPLE — " name prefix.
    """
    name = (provider_name or "").lower()
    return "mock" in name or "fixture" in name or "demo" in name or "sample" in name


def _executive_market_row(
    db: Session,
    product: Product,
    ranking: CountryRanking,
    *,
    price_source_pending: bool = False,
) -> dict:
    """One executive market: score + rationale + snapshot rows AS STORED (I1).

    ``score`` prefers the Stage-2 engine score, falling back to the Stage-1
    screen score; the rationale components and score confidence come verbatim
    from the persisted Stage-2 enrichment (``{}``/``None`` when Stage 2 has not
    run — a declared absence, never synthesized). Snapshot prices/competitors
    pass through exactly as stored, keeping whatever provenance fields the
    writer attached.
    """
    iso3 = ranking.importer_iso3
    iso2 = iso3_to_iso2(iso3)
    market = db.get(Market, iso2) if iso2 else None
    snapshot = _snapshot_for(db, product.hs_code, iso2)
    enrichment = ranking.enrichment or {}

    # The Stage-2 engine model score (0..1) and the Stage-1 screen score
    # (dollar-scale volume×growth) are on different scales — the report must
    # declare which one it is showing so the number is never misread (audit C8).
    if ranking.stage2_score is not None:
        score: float | None = float(ranking.stage2_score)
        score_model = enrichment.get("score_model") or "silk_market_ranker"
    elif ranking.screen_score is not None:
        score = float(ranking.screen_score)
        score_model = "stage1_screen"
    else:
        score = None
        score_model = None
    raw_conf = enrichment.get("score_confidence")
    score_confidence = float(raw_conf) if raw_conf is not None else None
    rationale = {
        name: {
            "value": c.get("value"),
            "source": c.get("source"),
            "confidence": c.get("confidence"),
            "note": c.get("note"),
            "retrieved_at": c.get("retrieved_at"),
        }
        for name, c in (enrichment.get("score_components") or {}).items()
    }
    tags = [t for t in (ranking.tags or []) if t]
    prices = list(snapshot.observed_prices or []) if snapshot is not None else []

    return {
        "country": (market.name_en if market else None) or iso3,
        "iso3": iso3,
        "iso2": iso2,
        "score": score,
        "score_confidence": score_confidence,
        "score_model": score_model,
        "rationale_components": rationale,
        "tags": tags,
        # I9 — the transit-hub demotion stays visible in the executive summary.
        "transit_hub": any("transit" in t.lower() for t in tags),
        "prices": prices,
        # J3 — a gated (keyless) price slot with nothing persisted is a *pending
        # data source*, not a searched-and-empty market; prices persisted before
        # the gate (or by a keyed run) always render as stored (I1).
        "prices_note": PRICING_PENDING_LINE if price_source_pending and not prices else "",
        "competitors": (
            list(snapshot.top_exporters or [])[:EXEC_LIST_CAP] if snapshot is not None else []
        ),
        "buyers": _executive_buyers(db, product, iso2),
    }


def build_executive_result(db: Session, product: Product) -> dict:
    """The engine ``result`` plus the executive multi-market section.

    Same shape as :func:`build_engine_result` (so ``silk_render.build_view``
    consumes it unchanged) with ``result["executive"]`` added: the screening
    summary and the top-5 funnel markets, each carrying score + rationale
    provenance, the stored snapshot prices/competitors, and the top buyer
    matches. Zero analyses → ``executive["markets"] == []`` and the engine
    renders a declared-gap report (I1) — nothing is fabricated.
    """
    analysis = _latest_analysis(db, product)
    rankings = _analysis_rankings(db, analysis)
    result = _engine_result(db, product, rankings)
    pending = _price_source_pending()
    result["executive"] = {
        "screening": _screening_summary(analysis),
        "markets": [
            _executive_market_row(db, product, r, price_source_pending=pending)
            for r in rankings[:TOP_MARKETS]
        ],
    }
    return result

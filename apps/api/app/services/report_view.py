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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analysis, CountryRanking, Market, MarketSnapshot, Product
from app.providers.countries import iso3_to_iso2
from app.services.report import _hs_confidence

#: Top-N funnel markets carried into the full report (mirrors the funnel top-5).
TOP_MARKETS = 5


def _dp(
    value: float | None,
    source: str,
    note: str = "",
    data_year: int | None = None,
) -> dict:
    """Engine ``DataPoint``-shaped provenance dict.

    I1: a ``None`` value is a declared gap — confidence ``0.0`` and a
    ``no_record`` status, never a fabricated zero.
    """
    present = value is not None
    return {
        "value": value,
        "source": source,
        "confidence": 0.9 if present else 0.0,
        "note": note,
        "retrieved_at": None,
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


def _market_row(db: Session, product: Product, ranking: CountryRanking) -> dict:
    iso3 = ranking.importer_iso3
    iso2 = iso3_to_iso2(iso3)
    market = db.get(Market, iso2) if iso2 else None
    snapshot = None
    if product.hs_code and iso2:
        snapshot = db.scalar(
            select(MarketSnapshot).where(
                MarketSnapshot.hs_code == product.hs_code,
                MarketSnapshot.market_iso2 == iso2,
            )
        )

    # market_size — prefer the snapshot's live total, else the funnel screen value.
    if snapshot is not None and snapshot.total_import_usd is not None:
        usd: float | None = float(snapshot.total_import_usd)
        size_source = "comtrade"
    elif ranking.import_usd is not None:
        usd = float(ranking.import_usd)
        size_source = "world_trade"
    else:
        usd = None
        size_source = "world_trade"
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
            "market_size": _dp(usd, size_source, note, ranking.year),
            "saudi_position": _dp(
                saudi,
                "comtrade",
                "Saudi supplier share of this market"
                if saudi is not None
                else "Saudi not among the reported top suppliers",
                ranking.year,
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
            ),
        },
    }


def build_engine_result(db: Session, product: Product) -> dict:
    """Reconstitute an engine ``result`` from the product's latest analysis.

    Feeds ``silk_render.build_view``. Markets come from the persisted world-funnel
    shortlist (top 5), each carrying sourced ``market_size`` / ``saudi_position`` /
    ``competition`` figures and a declared-gap ``demand_capacity`` (I1). With no
    analysis yet, ``markets`` is empty and ``build_view`` renders a valid stub.
    """
    analysis = db.scalar(
        select(Analysis)
        .where(Analysis.product_id == product.id)
        .order_by(Analysis.created_at.desc())
    )
    rankings: list[CountryRanking] = []
    if analysis is not None:
        rankings = list(
            db.scalars(
                select(CountryRanking)
                .where(CountryRanking.analysis_id == analysis.id)
                .order_by(CountryRanking.rank)
            )
        )

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

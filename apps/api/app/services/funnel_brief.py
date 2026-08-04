"""Brief-first output for a world-funnel analysis (decision #7 non-negotiables).

Assembles the one-page brief for a funnel run: the decision, three decisive
numbers, competitive-position lines, and — never compressed away — a source line
under every figure and an explicit "limits of this report" section. A missing
figure is a declared gap, never a fabricated number (I1).

This is the funnel's brief (a new artifact for the world-scan capability); the
engine's full analyze() report still derives solely from silk_render.build_view.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analysis, CountryRanking, Product

#: A standing limit until Stage 2/3 live enrichment lands — stated honestly.
_STAGE1_LIMIT = (
    "Stage-1 local screen only — live enrichment (tariffs, PPP, competitors) not "
    "yet applied to the shortlist."
)


def _fmt_usd(v: float | None) -> str | None:
    if v is None:
        return None
    v = float(v)
    return f"${v / 1e6:,.1f}M" if abs(v) >= 1e6 else f"${v:,.0f}"


def _source_line(r: CountryRanking) -> str:
    """The provenance line shown under a figure — never omitted (decision #7)."""
    src = "world_trade"
    if r.import_usd is None:
        return f"{src} — no reported import data"
    year = f" · {r.year}" if r.year is not None else ""
    tags = [t for t in (r.tags or []) if t]
    tag_note = f" · {', '.join(tags)}" if tags else ""
    return f"{src}{year}{tag_note}"


def build_funnel_brief(db: Session, analysis: Analysis) -> dict:
    """Build the brief-first view for a funnel analysis as a JSON-safe dict."""
    rankings = list(
        db.scalars(
            select(CountryRanking)
            .where(CountryRanking.analysis_id == analysis.id)
            .order_by(CountryRanking.rank)
        )
    )
    product = db.get(Product, analysis.product_id) if analysis.product_id else None
    hs_code = product.hs_code if product else None
    top5 = rankings[:5]

    # --- decision -------------------------------------------------------
    hs_label = f"HS {hs_code}" if hs_code else "the confirmed HS code"
    if not top5:
        decision = f"No world-trade data available for {hs_label} — cannot rank markets."
    else:
        t = top5[0]
        val = _fmt_usd(t.import_usd) or "an undisclosed volume"
        decision = f"Top export market for {hs_label}: {t.importer_iso3} ({val})."

    # --- three decisive numbers (each carries its source line + year) ----
    decisive = [
        {
            "label": r.importer_iso3,
            "value": _fmt_usd(r.import_usd),  # None => declared gap (I1)
            "source": _source_line(r),
            "year": r.year,
        }
        for r in top5[:3]
    ]

    # --- competitive position -------------------------------------------
    position: list[str] = []
    if rankings:
        top_k = min(5, len(top5))
        screened = analysis.total_screened
        # Show the funnel transparently when we know the true world count;
        # otherwise fall back to the shortlist length (older runs) — honestly.
        if screened and screened >= len(rankings):
            position.append(
                f"Screened {screened} markets worldwide → shortlisted "
                f"{len(rankings)} → top {top_k}."
            )
        else:
            position.append(f"Shortlisted {len(rankings)} markets → top {top_k}.")
    hubs = [r for r in top5 if r.is_transit_hub]
    if hubs:
        names = ", ".join(r.importer_iso3 for r in hubs)
        position.append(
            f"{len(hubs)} transit hub(s) in the top 5 ({names}) — penalized, not "
            "silently ranked, because imports include re-exports."
        )

    # --- limits of this report (never compressed away — decision #7) -----
    limits: list[str] = []
    no_data = [r for r in top5 if r.import_usd is None]
    if no_data:
        names = ", ".join(r.importer_iso3 for r in no_data)
        limits.append(
            f"{len(no_data)} of the top markets ({names}) had no reported import "
            "data — shown as gaps, not zeros."
        )
    mirror = [r for r in top5 if r.is_mirror]
    if mirror:
        names = ", ".join(r.importer_iso3 for r in mirror)
        limits.append(f"Rows tagged mirror data ({names}) are partner-reported, not direct.")
    if hubs:
        limits.append(
            "Transit-hub volumes overstate genuine domestic demand; treat their "
            "raw import figures with care."
        )
    limits.append(_STAGE1_LIMIT)

    return {
        "analysis_id": str(analysis.id),
        "hs_code": hs_code,
        "decision": decision,
        "decisive_numbers": decisive,
        "competitive_position": position,
        "limits": limits,
    }

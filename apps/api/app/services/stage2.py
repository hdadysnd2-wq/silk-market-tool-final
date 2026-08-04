"""Funnel Stage 2: budgeted live enrichment of the Stage-1 shortlist → top 5.

Stage 1 screens every market locally (zero calls) and shortlists ~15-20. Stage 2
enriches that shortlist with budgeted macro/tariff signals (applied tariff, PPP)
— charging the per-analysis API budget (locked decision #5) and logging spend —
then re-ranks to the top 5. A tariff-adjusted, demand-weighted score refines the
raw Stage-1 volume screen: a lower applied tariff and higher purchasing power
raise a market's fit. A market whose enrichment fails keeps its Stage-1 score (a
declared gap recorded in ``enrichment``, I1) — never a fabricated signal.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Analysis, CountryRanking
from app.providers.registry import get_market_enrichment_provider
from app.services.api_budget import charge

log = get_logger(__name__)

#: PPP anchor used to normalise demand quality into a bounded multiplier.
_PPP_ANCHOR = 65_000.0


def stage2_score(screen_score: float, tariff_pct: float | None, ppp: float | None) -> float:
    """Refine the Stage-1 screen score with tariff drag + a mild PPP lift.

    Tariff is a direct drag (20% applied tariff → ×0.80); PPP nudges the score
    within ~[0.85, 1.15] around the anchor. Missing signals simply don't apply
    their factor — a gap lowers confidence, never fabricates a number (I1).
    """
    factor = 1.0
    if tariff_pct is not None:
        factor *= max(0.0, 1.0 - float(tariff_pct))
    if ppp is not None:
        factor *= 0.85 + min(0.30, max(0.0, float(ppp)) / _PPP_ANCHOR * 0.30)
    return round(float(screen_score) * factor, 4)


def enrich_shortlist(
    db: Session, analysis: Analysis, hs6: str, limit: int = 20
) -> list[CountryRanking]:
    """Enrich the persisted Stage-1 shortlist (budgeted) and re-rank to a top 5.

    Charges one call per market against the active API budget (decision #5);
    stops early and logs when the budget is exhausted, leaving the rest on their
    Stage-1 score. Returns the shortlist re-ordered by the Stage-2 score, with
    ``rank`` reassigned so the top-5 the report surfaces reflects Stage 2.
    """
    rows = list(
        db.scalars(
            select(CountryRanking)
            .where(CountryRanking.analysis_id == analysis.id)
            .order_by(CountryRanking.rank)
            .limit(limit)
        )
    )
    provider = get_market_enrichment_provider()
    enriched = 0
    for r in rows:
        if not charge(1, source="market_enrichment"):
            log.warning(
                "stage2_budget_exhausted",
                analysis_id=str(analysis.id),
                importer=r.importer_iso3,
            )
            break
        record = provider.enrich_market(r.importer_iso3, hs6)
        if record is None:
            # Declared gap (I1): keep the Stage-1 score, note the missing signal.
            r.enrichment = {
                "applied_tariff_pct": None,
                "ppp_gni_per_capita": None,
                "source": provider.name,
                "note": "enrichment unavailable",
            }
            r.stage2_score = float(r.screen_score)
            continue
        e = record.data
        r.enrichment = {
            "applied_tariff_pct": e.applied_tariff_pct,
            "ppp_gni_per_capita": e.ppp_gni_per_capita,
            "source": record.provider_name,
            "note": "",
        }
        r.stage2_score = stage2_score(
            float(r.screen_score), e.applied_tariff_pct, e.ppp_gni_per_capita
        )
        r.stage = 2
        enriched += 1

    # Re-rank the shortlist by the Stage-2 score (fallback to the Stage-1 screen
    # score for any row the budget didn't reach), stable on ISO3.
    def _key(r: CountryRanking) -> tuple[float, str]:
        score = float(r.stage2_score) if r.stage2_score is not None else float(r.screen_score)
        return (-score, r.importer_iso3)

    rows.sort(key=_key)
    for new_rank, r in enumerate(rows, start=1):
        r.rank = new_rank
    db.flush()
    log.info(
        "stage2_enriched",
        analysis_id=str(analysis.id),
        hs6=hs6,
        enriched=enriched,
        considered=len(rows),
    )
    return rows

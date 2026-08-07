"""The 3-stage world funnel — Stage 1: screen every market locally (zero API calls).

Stage 1 is a single SQL query over the precomputed ``world_trade`` table: for one
HS6, rank every importer in the world by import volume **modulated by its
multi-year trend** (locked decision #8) for the latest available year — the
scoring itself is delegated to the engine (``silk_market_ranker``), so the
platform keeps no parallel scorer. The **transit-port guard (I9)** is applied
here — re-export hubs (AE, NL,
SG, HK, BE, …), whose import volumes are inflated by transshipment, carry a
visible tag *and* a score penalty so they do not silently top the ranking.
Mirror-derived rows carry a "mirror data" tag; a missing figure is surfaced as a
declared gap, never a fabricated number (I1).

Stages 2 (budgeted live enrichment of the top-20% shortlist, clamped 5–30) and 3
(full agent deep-dive on the
top 5) run on the shortlist this stage produces — they are not this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import WorldTrade
from app.services import engine

#: I9 — transit hubs must not silently top the ranking. Their screening score is
#: multiplied by this factor (imports include re-exports, so raw volume overstates
#: genuine domestic demand). The penalty is visible, not silent: the tag below is
#: attached too, so the report can show *why* the market was demoted.
#: NOTE: the engine's fine-grained ranker applies its own, milder 0.25 penalty
#: (silk_market_ranker._TRANSIT_HUB_PENALTY). The difference is deliberate —
#: Stage 1 is a coarse volume screen where inflated re-export volume dominates,
#: so it discounts harder; the Stage-2/3 ranker weighs many non-volume signals
#: and needs less correction. Documented in docs/BACKLOG.md (ADR-0003 section).
TRANSIT_PENALTY = 0.5

TRANSIT_HUB_TAG = "transit hub — imports include re-exports"
MIRROR_TAG = "mirror data"
NO_DATA_TAG = "no data"


@dataclass
class ScreenedMarket:
    """One importer's Stage-1 screening result for an HS6."""

    importer_iso3: str
    year: int
    import_usd: float | None
    yoy_growth: float | None
    cagr_3y: float | None
    is_transit_hub: bool
    is_mirror: bool
    #: Volume-based screening score after the transit penalty (0 when no data).
    screen_score: float
    tags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "importer_iso3": self.importer_iso3,
            "year": self.year,
            "import_usd": self.import_usd,
            "yoy_growth": self.yoy_growth,
            "cagr_3y": self.cagr_3y,
            "is_transit_hub": self.is_transit_hub,
            "is_mirror": self.is_mirror,
            "screen_score": self.screen_score,
            "tags": list(self.tags),
        }


@dataclass
class Stage1Result:
    """The full Stage-1 outcome — the ranked shortlist plus funnel transparency."""

    hs6: str
    year: int | None
    total_screened: int
    markets: list[ScreenedMarket]
    #: Markets with actual import data (the shortlist quota base); the rest are
    #: declared no-data gaps (I1) that cannot meaningfully compete for a slot.
    covered: int = 0
    #: How many markets were kept for Stage 2 (funnel transparency:
    #: "screened N → shortlisted M → top 5").
    shortlisted: int = 0

    def as_dict(self) -> dict:
        return {
            "hs6": self.hs6,
            "year": self.year,
            "total_screened": self.total_screened,
            "covered": self.covered,
            "shortlisted": self.shortlisted,
            "markets": [m.as_dict() for m in self.markets],
        }


#: J1 shortlist quota — Stage 1 keeps the top ``SHORTLIST_FRACTION`` of covered
#: markets (ceil), clamped to [SHORTLIST_MIN, SHORTLIST_MAX]. The clamp bounds
#: the budgeted Stage-2 pass: never fewer than 5 candidates for a thin market,
#: never more than 30 live-enrichment charges for a huge one.
SHORTLIST_FRACTION = 0.20
SHORTLIST_MIN = 5
SHORTLIST_MAX = 30


def shortlist_quota(covered: int) -> int:
    """ceil(20% of covered markets), clamped to [5, 30] (bounded Stage-2 budget).

    Zero coverage is the one case the [5, 30] clamp must not lift off the floor:
    with no market carrying import data, every candidate is a declared no-data gap
    (I1) that scores 0, so shortlisting (and Stage-2-enriching) 5 of them just
    spends the per-analysis API budget on markets that can never rank. Return 0.
    """
    if covered <= 0:
        return 0
    return max(SHORTLIST_MIN, min(SHORTLIST_MAX, math.ceil(covered * SHORTLIST_FRACTION)))


#: Substring marking a ``world_trade`` row as demo-seed data (see seeds/seed.py).
_DEMO_SOURCE_MARK = "demo seed"


def _latest_year(db: Session, hs6: str) -> int | None:
    return db.scalar(select(func.max(WorldTrade.year)).where(WorldTrade.hs6 == hs6))


def coverage_state(db: Session, hs6: str) -> str:
    """Classify the ``world_trade`` coverage for ``hs6``: none | demo | live.

    ``none``  — no rows at all (the screen would silently produce an empty funnel).
    ``demo``  — rows exist but every one is demo-seed data (not real trade data).
    ``live``  — at least one row came from a real sync.

    The world funnel uses this to fail loudly on ``none`` and to flag a ``demo``
    result, instead of presenting demo/absent data as a genuine world screen.
    """
    sources = db.scalars(
        select(func.distinct(WorldTrade.source)).where(WorldTrade.hs6 == hs6)
    ).all()
    if not sources:
        return "none"
    if all(_DEMO_SOURCE_MARK in (s or "") for s in sources):
        return "demo"
    return "live"


def screen_world(db: Session, hs6: str, top_n: int | None = None) -> Stage1Result:
    """Screen every importer for ``hs6`` in the latest available year (Stage 1).

    Returns the ranked shortlist with the transit-port guard (I9) applied and
    provenance tags attached. The shortlist size defaults to the top-20% cut
    (:func:`shortlist_quota` — ceil(20%) of *covered* markets, clamped to
    [5, 30] to bound the Stage-2 budget); an explicit ``top_n`` overrides it.
    ``total_screened`` / ``covered`` / ``shortlisted`` expose the funnel
    transparently ("screened N markets → shortlisted M …").
    """
    year = _latest_year(db, hs6)
    if year is None:
        return Stage1Result(hs6=hs6, year=None, total_screened=0, markets=[])

    rows = list(
        db.scalars(select(WorldTrade).where(WorldTrade.hs6 == hs6, WorldTrade.year == year))
    )
    screened = [_screen_row(r) for r in rows]
    # Deterministic order: score desc, then ISO3 asc as a stable tiebreak.
    screened.sort(key=lambda m: (-m.screen_score, m.importer_iso3))
    # Coverage = markets holding actual import data; no-data rows are declared
    # gaps (I1) that score 0 and must not inflate the percentage base.
    covered = sum(1 for m in screened if m.import_usd is not None)
    keep = top_n if top_n is not None else shortlist_quota(covered)
    kept = screened[:keep]
    return Stage1Result(
        hs6=hs6,
        year=year,
        total_screened=len(screened),
        covered=covered,
        shortlisted=len(kept),
        markets=kept,
    )


def _screen_row(row: WorldTrade) -> ScreenedMarket:
    tags: list[str] = []
    if row.import_usd is None:
        tags.append(NO_DATA_TAG)  # I1 — declared gap, scored as 0 not fabricated
    if row.is_mirror:
        tags.append(MIRROR_TAG)

    # The engine owns the screening score (decision #8: the multi-year trend
    # feeds it — a growing market outranks a flat one of equal volume). A missing
    # volume returns 0.0 there (declared gap, I1), never a fabricated number.
    score = engine.stage1_screen_score(row.import_usd, row.cagr_3y, row.yoy_growth)
    if row.is_transit_hub:
        # I9 — penalize AND flag; never let a re-export hub silently top the list.
        score *= TRANSIT_PENALTY
        tags.append(TRANSIT_HUB_TAG)

    return ScreenedMarket(
        importer_iso3=row.importer_iso3,
        year=row.year,
        import_usd=float(row.import_usd) if row.import_usd is not None else None,
        yoy_growth=float(row.yoy_growth) if row.yoy_growth is not None else None,
        cagr_3y=float(row.cagr_3y) if row.cagr_3y is not None else None,
        is_transit_hub=row.is_transit_hub,
        is_mirror=row.is_mirror,
        screen_score=score,
        tags=tags,
    )

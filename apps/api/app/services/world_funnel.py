"""The 3-stage world funnel — Stage 1: screen every market locally (zero API calls).

Stage 1 is a single SQL query over the precomputed ``world_trade`` table: for one
HS6, rank every importer in the world by import volume for the latest available
year. The **transit-port guard (I9)** is applied here — re-export hubs (AE, NL,
SG, HK, BE, …), whose import volumes are inflated by transshipment, carry a
visible tag *and* a score penalty so they do not silently top the ranking.
Mirror-derived rows carry a "mirror data" tag; a missing figure is surfaced as a
declared gap, never a fabricated number (I1).

Stages 2 (budgeted live enrichment of ~15–20) and 3 (full agent deep-dive on the
top 5) run on the shortlist this stage produces — they are not this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import WorldTrade

#: I9 — transit hubs must not silently top the ranking. Their screening score is
#: multiplied by this factor (imports include re-exports, so raw volume overstates
#: genuine domestic demand). The penalty is visible, not silent: the tag below is
#: attached too, so the report can show *why* the market was demoted.
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

    def as_dict(self) -> dict:
        return {
            "hs6": self.hs6,
            "year": self.year,
            "total_screened": self.total_screened,
            "markets": [m.as_dict() for m in self.markets],
        }


def _latest_year(db: Session, hs6: str) -> int | None:
    return db.scalar(select(func.max(WorldTrade.year)).where(WorldTrade.hs6 == hs6))


def screen_world(db: Session, hs6: str, top_n: int = 20) -> Stage1Result:
    """Screen every importer for ``hs6`` in the latest available year (Stage 1).

    Returns the ranked shortlist (up to ``top_n``) with the transit-port guard
    (I9) applied and provenance tags attached. ``total_screened`` is the full
    count of markets considered, so the report can show the funnel transparently
    ("screened N markets → shortlisted …").
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
    return Stage1Result(hs6=hs6, year=year, total_screened=len(screened), markets=screened[:top_n])


def _screen_row(row: WorldTrade) -> ScreenedMarket:
    tags: list[str] = []
    volume = float(row.import_usd) if row.import_usd is not None else 0.0
    if row.import_usd is None:
        tags.append(NO_DATA_TAG)  # I1 — declared gap, scored as 0 not fabricated
    if row.is_mirror:
        tags.append(MIRROR_TAG)

    score = volume
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

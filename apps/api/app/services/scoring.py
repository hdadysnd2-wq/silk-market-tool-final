"""Buyer relevance scoring — a pure, side-effect-free function.

The score is a weighted sum over six factors and always returns the per-factor
breakdown alongside the total, so the UI can explain *why* a buyer ranks where
it does rather than showing an opaque number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.providers.base import SOURCE_QUALITY, SourceType
from app.services.normalization import hs_match_depth

#: Maximum points per factor. They sum to 100.
WEIGHTS: dict[str, int] = {
    "hs_match": 30,
    "volume": 20,
    "recency": 15,
    "geography": 10,
    "size_fit": 10,
    "source_quality": 15,
}

_HS_DEPTH_FRACTION = {"hs6": 1.0, "hs4": 0.6, "hs2": 0.3, "none": 0.0}

#: Buyer countries where a Saudi exporter has a freight/logistics edge.
_GEO_ADVANTAGED = {"AE", "QA", "KW", "BH", "OM", "EG", "JO", "IN", "PK"}


@dataclass(frozen=True)
class ScoringInput:
    product_hs_code: str
    buyer_hs_codes: list[str]
    shipment_count_12m: int
    total_value_usd_12m: float
    days_since_last_shipment: int | None
    buyer_country_iso2: str
    employee_count: int | None
    source: SourceType


@dataclass(frozen=True)
class ScoreBreakdown:
    total: int
    factors: dict[str, dict] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"total": self.total, "factors": self.factors}


def _factor(points: float, max_points: int, detail: str) -> dict:
    return {
        "points": round(points, 1),
        "max": max_points,
        "detail": detail,
    }


def score_buyer(inp: ScoringInput) -> ScoreBreakdown:
    factors: dict[str, dict] = {}

    # 1. HS-code match depth — the single strongest signal.
    best_depth = "none"
    for code in inp.buyer_hs_codes:
        depth = hs_match_depth(inp.product_hs_code, code)
        if _HS_DEPTH_FRACTION[depth] > _HS_DEPTH_FRACTION[best_depth]:
            best_depth = depth
    hs_points = WEIGHTS["hs_match"] * _HS_DEPTH_FRACTION[best_depth]
    factors["hs_match"] = _factor(
        hs_points, WEIGHTS["hs_match"], f"Import history matches at {best_depth.upper()} level"
    )

    # 2. Import volume & frequency (log-shaped saturation).
    freq_fraction = min(1.0, inp.shipment_count_12m / 24.0)
    value_fraction = min(1.0, inp.total_value_usd_12m / 1_000_000.0)
    volume_fraction = 0.6 * freq_fraction + 0.4 * value_fraction
    volume_points = WEIGHTS["volume"] * volume_fraction
    factors["volume"] = _factor(
        volume_points,
        WEIGHTS["volume"],
        f"{inp.shipment_count_12m} shipments / "
        f"${inp.total_value_usd_12m:,.0f} in the last 12 months",
    )

    # 3. Recency of the last shipment.
    if inp.days_since_last_shipment is None:
        recency_fraction = 0.0
        recency_detail = "No recent shipment on record"
    else:
        days = inp.days_since_last_shipment
        recency_fraction = max(0.0, 1.0 - days / 365.0)
        recency_detail = f"Last shipment {days} days ago"
    recency_points = WEIGHTS["recency"] * recency_fraction
    factors["recency"] = _factor(recency_points, WEIGHTS["recency"], recency_detail)

    # 4. Geography fit — logistics advantage from Saudi Arabia.
    advantaged = inp.buyer_country_iso2.upper() in _GEO_ADVANTAGED
    geo_points = WEIGHTS["geography"] * (1.0 if advantaged else 0.5)
    factors["geography"] = _factor(
        geo_points,
        WEIGHTS["geography"],
        "Freight-advantaged lane from KSA" if advantaged else "Standard shipping lane",
    )

    # 5. Company-size fit — mid-size importers convert best.
    size_fraction, size_detail = _size_fit(inp.employee_count)
    size_points = WEIGHTS["size_fit"] * size_fraction
    factors["size_fit"] = _factor(size_points, WEIGHTS["size_fit"], size_detail)

    # 6. Source quality — customs data beats a Maps listing.
    quality = SOURCE_QUALITY.get(inp.source, 0.4)
    source_points = WEIGHTS["source_quality"] * quality
    factors["source_quality"] = _factor(
        source_points,
        WEIGHTS["source_quality"],
        f"Evidence source: {inp.source.value}",
    )

    total = round(sum(f["points"] for f in factors.values()))
    return ScoreBreakdown(total=min(100, max(0, total)), factors=factors)


def _size_fit(employee_count: int | None) -> tuple[float, str]:
    if employee_count is None:
        return 0.5, "Company size unknown"
    if 20 <= employee_count <= 500:
        return 1.0, f"{employee_count} employees — ideal mid-market importer"
    if employee_count < 20:
        return 0.5, f"{employee_count} employees — small buyer"
    return 0.7, f"{employee_count} employees — large buyer"


def days_between(earlier: date, later: date) -> int:
    return (later - earlier).days

"""فحوص جودة البيانات لسِلك — Silk data-quality checks (flag, never change).

Catches the README failure modes (near-zero import totals from an HS-version /
subheading mismatch, half-missing components, etc.) by FLAGGING ranker rows.
Pure logic over the row + its component DataPoints. Offline, stdlib only.
Never edits the underlying numbers — it only attaches human-readable flags.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# عتبة "شبه الصفر" لحجم السوق — below this (USD) an import total looks like a
# wrong subheading / HS-version mismatch rather than a real tiny market.
_NEAR_ZERO_USD = 1000.0


def _dp_value(comp: object) -> object:
    """استخرج value من DataPoint أو dict — pull .value whether DataPoint or dict."""
    if comp is None:
        return None
    if isinstance(comp, dict):
        return comp.get("value")
    return getattr(comp, "value", None)


def validate_market_row(row: dict) -> list[str]:
    """افحص صف سوق وأعد تنبيهات — return human-readable quality flags for one row.

    Pure logic over row["components"] (DataPoints or dicts). No network, no
    mutation. Empty list => no concerns detected.
    """
    flags: list[str] = []
    comps = row.get("components", {}) or {}

    size = _dp_value(comps.get("market_size"))
    saudi = _dp_value(comps.get("saudi_position"))
    demand = _dp_value(comps.get("demand_capacity"))
    competition = _dp_value(comps.get("competition"))

    present = [v for v in (size, saudi, demand, competition) if v is not None]
    if not present:
        flags.append("all components missing — no usable data for this market")
        return flags

    if size is not None and 0.0 <= float(size) < _NEAR_ZERO_USD:
        flags.append("market_size suspiciously near-zero (possible "
                     "HS-version/subheading mismatch)")

    if size is None and saudi is not None:
        flags.append("saudi_position present but market_size missing "
                     "(cannot weigh entry without market size)")

    if demand is None:
        flags.append("demand_capacity missing (no income/population signal)")

    # حصة سعودية فوق 100% مستحيلة — share must be a sane percentage.
    if saudi is not None and not (0.0 <= float(saudi) <= 100.0):
        flags.append(f"saudi_position share out of range ({saudi}%) — bad data")

    # HHI خارج [0,1] يعني خطأ حساب — concentration must be a fraction.
    if competition is not None and not (0.0 <= float(competition) <= 1.0):
        flags.append(f"competition HHI out of range ({competition}) — bad data")

    return flags


def annotate_result(result: dict) -> dict:
    """علّم نتيجة المحرّك بتنبيهات الجودة — attach quality flags, never change numbers.

    Adds row["quality_flags"] to each market and a top-level
    result["quality_summary"] (counts). Returns the same dict (mutated).
    """
    markets = result.get("markets", []) or []
    flagged_rows = 0
    total_flags = 0
    for row in markets:
        row_flags = validate_market_row(row)
        row["quality_flags"] = row_flags
        if row_flags:
            flagged_rows += 1
            total_flags += len(row_flags)

    result["quality_summary"] = {
        "markets_checked": len(markets),
        "markets_flagged": flagged_rows,
        "total_flags": total_flags,
        "note": "تنبيهات جودة فقط؛ الأرقام لم تُغيّر — quality flags only; "
                "underlying numbers unchanged.",
    }
    log.info("quality: %d/%d markets flagged (%d flags)",
             flagged_rows, len(markets), total_flags)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # صفّان وهميان (هيكل فقط، ليست بيانات سوق حقيقية) — fake rows, STRUCTURE only.
    near_zero = {
        "country": "Demo-A", "iso3": "AAA", "total_score": 0.0, "confidence": 0.5,
        "components": {
            "market_size": {"value": 12.0},        # near-zero -> mismatch flag
            "saudi_position": {"value": 3.0},
            "demand_capacity": {"value": 9.9e12},
            "competition": {"value": 0.4},
        },
    }
    empty = {
        "country": "Demo-B", "iso3": "BBB", "total_score": 0.0, "confidence": 0.0,
        "components": {
            "market_size": {"value": None}, "saudi_position": {"value": None},
            "demand_capacity": {"value": None}, "competition": {"value": None},
        },
    }
    print("row A flags:", validate_market_row(near_zero))
    print("row B flags:", validate_market_row(empty))
    demo = {"product": "demo", "markets": [near_zero, empty]}
    annotate_result(demo)
    print("summary:", demo["quality_summary"])

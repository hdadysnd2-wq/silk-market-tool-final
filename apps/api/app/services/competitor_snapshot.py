"""Competitor snapshot: who else exports this HS code into the target market.

Backed by UN Comtrade aggregates, cached per (hs_code, market) so repeated views
don't re-hit the API.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarketSnapshot, utcnow
from app.providers.registry import get_comtrade_provider


def build_snapshot(
    db: Session, hs_code: str, market_iso2: str, refresh: bool = False
) -> MarketSnapshot:
    snapshot = db.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.hs_code == hs_code,
            MarketSnapshot.market_iso2 == market_iso2,
        )
    )
    if snapshot is not None and not refresh:
        return snapshot

    comtrade = get_comtrade_provider()
    flows = comtrade.trade_flows(hs_code, market_iso2, years=3)
    exporters = comtrade.top_exporters(hs_code, market_iso2, limit=10)

    yearly = [
        {"year": r.data.year, "value_usd": r.data.value_usd}
        for r in sorted(flows, key=lambda r: r.data.year)
    ]
    total_import = yearly[-1]["value_usd"] if yearly else None
    trend = _trend_pct(yearly)
    top = [
        {
            "exporter_iso2": r.data.exporter_iso2,
            "exporter_name": r.data.exporter_name,
            "value_usd": r.data.value_usd,
            "share_pct": r.data.share_pct,
            # Per-row DataPoint provenance (Wave 3 item 3): every competitor
            # figure carries its own source/confidence/observation time, not
            # just the snapshot-level fetched_at.
            "source": r.provider_name,
            "confidence": r.confidence,
            "retrieved_at": r.fetched_at.isoformat() if r.fetched_at else None,
        }
        for r in exporters
    ]

    # Snapshot-level provenance reflects the ACTUAL origin of the records, not a
    # hardcoded "comtrade": an offline/degraded fixture serves as
    # "comtrade_fixture" (audit C7) so the stored snapshot and the executive
    # report never present fixture numbers as genuine live UN Comtrade (I1).
    origin = (flows or exporters)
    actual_source = origin[0].provider_name if origin else "comtrade"

    if snapshot is None:
        snapshot = MarketSnapshot(hs_code=hs_code, market_iso2=market_iso2)
        db.add(snapshot)
    snapshot.total_import_usd = total_import
    snapshot.trend_pct = trend
    snapshot.top_exporters = top
    snapshot.yearly_values = yearly
    snapshot.source = actual_source
    snapshot.provider_name = actual_source
    snapshot.fetched_at = utcnow()
    db.flush()
    return snapshot


def _trend_pct(yearly: list[dict]) -> float | None:
    if len(yearly) < 2:
        return None
    first, last = yearly[0]["value_usd"], yearly[-1]["value_usd"]
    if not first:
        return None
    return round(100 * (last - first) / first, 1)

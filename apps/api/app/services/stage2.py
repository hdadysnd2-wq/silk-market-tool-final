"""Funnel Stage 2: budgeted live enrichment of the Stage-1 shortlist → top 5.

Stage 1 screens every market locally (zero calls) and shortlists the top 20% of
covered markets (clamped to 5–30, J1). Stage 2
enriches that shortlist with budgeted macro/tariff signals (applied tariff, PPP)
— charging the per-analysis API budget (locked decision #5) and logging spend —
then re-ranks with the ENGINE's audited weighted component model (Wave 3 item 2:
``engine.score_market_components`` → ``silk_market_ranker.score_component_rows``
— weights, per-cohort normalization, renormalization over present components,
inversion of competition/tariff/distance, I9 transit-hub demotion). The platform
supplies its own persisted signals as components (J1, seven total): import
volume (``world_trade``), PPP GNI/capita (demand-capacity proxy), the Saudi
supplier share and top-supplier concentration (when a ``MarketSnapshot``
exists), the observed Comtrade unit value (``import_usd/import_qty`` from
``world_trade``), the applied tariff from the enrichment record, and the derived
great-circle distance from Jeddah (``providers.countries_distance``). A missing
signal is a skipped component that lowers that row's score confidence (I1) —
never fabricated.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Analysis, CountryRanking, MarketSnapshot, WorldTrade
from app.providers.countries import iso3_to_iso2
from app.providers.countries_distance import DISTANCE_SOURCE, distance_from_jeddah_km
from app.providers.registry import get_market_enrichment_provider
from app.services import heartbeat
from app.services.api_budget import charge

log = get_logger(__name__)


def _unit_price(db: Session, hs6: str, r: CountryRanking) -> float | None:
    """Observed Comtrade unit value (USD per reported qty unit) for this market.

    Derived from the persisted ``world_trade`` row: ``import_usd / import_qty``.
    A row without a positive quantity is a declared gap (I1) — returns ``None``
    so the component is omitted, never a fabricated unit value.
    """
    row = db.scalar(
        select(WorldTrade).where(
            WorldTrade.hs6 == hs6,
            WorldTrade.importer_iso3 == r.importer_iso3,
            WorldTrade.year == r.year,
        )
    )
    if row is None or row.import_usd is None or row.import_qty is None:
        return None
    qty = float(row.import_qty)
    if qty <= 0:
        return None
    return float(row.import_usd) / qty


def _components_for(
    db: Session, hs6: str, r: CountryRanking, ppp: float | None, ppp_source: str
) -> dict[str, dict]:
    """The engine's seven scoring components from the platform's persisted data.

    Every component carries its source; an absent signal is simply omitted so
    the engine skips it (renormalizing and lowering confidence) — no fabricated
    values (I1).
    """
    from app.services.report_view import _saudi_share, _top_supplier_share

    components: dict[str, dict] = {}
    if r.import_usd is not None:
        components["market_size"] = {
            "value": float(r.import_usd),
            "source": "world_trade",
            "confidence": 0.9,
            "note": f"total imports HS{hs6} {r.year}",
        }
    if ppp is not None:
        components["demand_capacity"] = {
            "value": float(ppp),
            "source": ppp_source,
            "confidence": 0.9,
            "note": "PPP GNI/capita (population unavailable — capacity proxy)",
        }
    iso2 = iso3_to_iso2(r.importer_iso3)
    snapshot = None
    if iso2:
        snapshot = db.scalar(
            select(MarketSnapshot).where(
                MarketSnapshot.hs_code == hs6, MarketSnapshot.market_iso2 == iso2
            )
        )
    saudi = _saudi_share(snapshot)
    if saudi is not None:
        components["saudi_position"] = {
            # Percent-points (30.0 for 30%), the engine narrative unit contract
            # (silk_market_ranker._saudi_position_component). The executive
            # rationale line renders this with fmt_pct — a 0..1 fraction here
            # printed 0.3% for a real 30% share (audit C9). Cohort-normalized
            # scoring is unaffected by the ×100.
            "value": saudi * 100.0,
            "source": snapshot.source or "comtrade",
            "confidence": 0.9,
            "note": "Saudi supplier share of this market",
        }
    concentration = _top_supplier_share(snapshot)
    if concentration is not None:
        components["competition"] = {
            "value": concentration,
            "source": snapshot.source or "comtrade",
            "confidence": 0.9,
            "note": "largest-supplier concentration",
        }
    # J1 — the three new components, each from REAL persisted/derived data only.
    unit_price = _unit_price(db, hs6, r)
    if unit_price is not None:
        components["unit_price_level"] = {
            "value": unit_price,
            "source": "world_trade",
            "confidence": 0.8,
            "note": "Comtrade unit value USD/qty",
        }
    tariff = (r.enrichment or {}).get("applied_tariff_pct")
    if tariff is not None:
        components["tariff_access"] = {
            "value": float(tariff),
            "source": (r.enrichment or {}).get("source") or "enrichment",
            "confidence": 0.8,
            "note": "applied import tariff for HS6",
        }
    distance_km = distance_from_jeddah_km(r.importer_iso3)
    if distance_km is not None:
        components["logistics_proximity"] = {
            "value": distance_km,
            "source": DISTANCE_SOURCE,
            "confidence": 0.9,
            "note": "great-circle km, Jeddah → market's main port",
        }
    return components


def enrich_shortlist(
    db: Session, analysis: Analysis, hs6: str, limit: int | None = None
) -> list[CountryRanking]:
    """Enrich the persisted Stage-1 shortlist (budgeted) and re-rank to a top 5.

    Charges one call per market against the active API budget (decision #5);
    stops early and logs when the budget is exhausted, leaving the rest on their
    Stage-1 score. Returns the shortlist re-ordered by the Stage-2 score, with
    ``rank`` reassigned so the top-5 the report surfaces reflects Stage 2.
    ``limit`` defaults to the *entire* persisted Stage-1 shortlist so it is
    re-ranked as ONE cohort — a partial re-rank would leave stale Stage-1 ranks
    below the cut line. The default no longer caps at ``SHORTLIST_MAX``: Stage 1
    already clamps its own shortlist, but an explicit ``top_n`` > that ceiling
    can persist more rows, and a hardcoded 30 here would strand rows 31+ on their
    Stage-1 rank/stage. The per-analysis API budget still bounds live-enrichment
    charges independently of this row count.
    """
    query = (
        select(CountryRanking)
        .where(CountryRanking.analysis_id == analysis.id)
        .order_by(CountryRanking.rank)
    )
    if limit is not None:
        query = query.limit(limit)
    rows = list(db.scalars(query))
    provider = get_market_enrichment_provider()
    enriched = 0
    ppp_by_iso3: dict[str, tuple[float | None, str]] = {}
    for r in rows:
        # Liveness beat per market: a live enrichment pass can legitimately take
        # minutes; without this the stuck-row reaper cannot tell it from a lost
        # worker (symptom B).
        heartbeat.beat(analysis.id)
        if not charge(1, source="market_enrichment"):
            log.warning(
                "stage2_budget_exhausted",
                analysis_id=str(analysis.id),
                importer=r.importer_iso3,
            )
            break
        record = provider.enrich_market(r.importer_iso3, hs6)
        if record is None:
            # Declared gap (I1): note the missing signal; the scorer below skips
            # the absent components and lowers this row's score confidence.
            r.enrichment = {
                "applied_tariff_pct": None,
                "ppp_gni_per_capita": None,
                "source": provider.name,
                "note": "enrichment unavailable",
            }
            ppp_by_iso3[r.importer_iso3] = (None, provider.name)
            continue
        e = record.data
        r.enrichment = {
            "applied_tariff_pct": e.applied_tariff_pct,
            "ppp_gni_per_capita": e.ppp_gni_per_capita,
            "source": record.provider_name,
            "note": "",
        }
        ppp_by_iso3[r.importer_iso3] = (e.ppp_gni_per_capita, record.provider_name)
        r.stage = 2
        enriched += 1

    # Score the WHOLE cohort with the engine's weighted model — normalization is
    # per-cohort, so every row is scored together (rows the budget didn't reach
    # simply contribute fewer components).
    component_rows = []
    for r in rows:
        ppp, ppp_source = ppp_by_iso3.get(r.importer_iso3, (None, provider.name))
        components = _components_for(db, hs6, r, ppp, ppp_source)
        component_rows.append({"iso3": r.importer_iso3, "components": components})
    from app.services import engine

    scored = engine.score_market_components(component_rows)
    for r, s, crow in zip(rows, scored, component_rows, strict=True):
        r.stage2_score = s["total_score"]
        r.enrichment = {
            **(r.enrichment or {}),
            # Score provenance: which components fed the engine model and the
            # per-row confidence (fewer present components = lower confidence).
            "score_components": {name: dict(c) for name, c in crow["components"].items()},
            "score_confidence": s["confidence"],
            "score_model": "silk_market_ranker",
        }

    # Re-rank the shortlist by the engine score, stable on ISO3.
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

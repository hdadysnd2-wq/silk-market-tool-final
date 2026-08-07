"""Regression locks: competitor figures persist full DataPoint provenance (W3 item 3).

The competitor/price path already delegates to the engine's agents (the
localprice adapter wraps the PAID LocalPriceAgent; the comtrade adapter wraps
silk_data_layer — the CompetitionAgent's source), and every ProviderRecord
carries source/confidence/fetched_at — but persistence DROPPED the confidence
and observation time. Every stored competitor row and observed price now
answers "who said it, how sure, and when" from Postgres alone.
"""

from __future__ import annotations

from app.models import MarketSnapshot
from app.services import engine
from app.services.competitor_snapshot import build_snapshot
from app.services.observed_prices import fetch_prices_for_market


def test_snapshot_exporters_carry_row_level_provenance(db, market):
    snapshot = build_snapshot(db, "392010", "IN")
    assert snapshot.top_exporters, "mock comtrade returns exporters"
    for row in snapshot.top_exporters:
        assert row["source"], row
        assert isinstance(row["confidence"], float)
        assert row["retrieved_at"], "observation time must persist per row"


def test_observed_prices_carry_confidence_and_retrieved_at(db, factory, product, market):
    with engine.deepen_scope(True):
        out = fetch_prices_for_market(db, product, "IN")
    assert out["skipped"] is False and out["count"] > 0

    snapshot = db.query(MarketSnapshot).filter_by(hs_code="392010", market_iso2="IN").one()
    for price in snapshot.observed_prices:
        assert price["price"] is not None  # only observed listings persist (I1)
        assert price["source"]
        assert isinstance(price["confidence"], float)
        assert price["retrieved_at"]


def test_outside_deepen_no_prices_are_fetched(db, factory, product, market):
    out = fetch_prices_for_market(db, product, "IN")
    assert out["skipped"] is True  # I5 — the paid layer never runs outside deepen

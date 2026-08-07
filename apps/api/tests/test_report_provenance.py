"""Regression locks: report_view carries real provenance, never a synthesized one.

``_dp()`` used to stamp confidence=0.9 on every present value — provenance
theater in a codebase whose central ethos is "every number carries its source".
A present value now carries ``confidence=None`` ("not scored"; the engine's
``confidence_phrase`` renders that honestly) unless a real upstream score
exists, and ``retrieved_at`` is threaded from the actual fetch/write timestamps
instead of being discarded.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import MarketSnapshot
from app.services.report_view import build_engine_result
from tests.test_report_docx import _seed_funnel, _snapshot_with_saudi

_FETCHED = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _components(db, product):
    result = build_engine_result(db, product)
    markets = {m["iso3"]: m for m in result["markets"]}
    return markets["DEU"]["components"]


def test_present_values_carry_no_synthesized_confidence(db, factory, product):
    _seed_funnel(db, product)
    _snapshot_with_saudi(db, product.hs_code)
    db.query(MarketSnapshot).update({"fetched_at": _FETCHED})
    db.commit()

    comps = _components(db, product)
    for name in ("market_size", "saudi_position", "competition"):
        dp = comps[name]
        assert dp["value"] is not None
        # No upstream numeric confidence exists for these figures — None is the
        # truthful value; 0.9 was fabricated.
        assert dp["confidence"] is None, name
        assert dp["confidence"] != 0.9, name


def test_snapshot_fetched_at_flows_into_retrieved_at(db, factory, product):
    _seed_funnel(db, product)
    _snapshot_with_saudi(db, product.hs_code)
    db.query(MarketSnapshot).update({"fetched_at": _FETCHED})
    db.commit()

    comps = _components(db, product)
    assert comps["market_size"]["retrieved_at"] == _FETCHED.isoformat()
    assert comps["saudi_position"]["retrieved_at"] == _FETCHED.isoformat()
    assert comps["competition"]["retrieved_at"] == _FETCHED.isoformat()


def test_world_trade_fallback_uses_ranking_write_time(db, factory, product):
    # No snapshot: market_size falls back to the funnel screen value, whose
    # provenance timestamp is when the ranking row was written.
    _seed_funnel(db, product)
    comps = _components(db, product)
    assert comps["market_size"]["value"] is not None
    assert comps["market_size"]["retrieved_at"] is not None

    from datetime import datetime as _dt

    _dt.fromisoformat(comps["market_size"]["retrieved_at"])  # parseable ISO


def test_declared_gaps_keep_zero_confidence_and_no_record(db, factory, product):
    _seed_funnel(db, product)
    comps = _components(db, product)
    gap = comps["demand_capacity"]
    assert gap["value"] is None
    assert gap["confidence"] == 0.0
    assert gap["status"] == "no_record"
    assert gap["retrieved_at"] is None


def test_docx_renders_with_unscored_confidence(db, factory, product, tmp_path):
    # The full render path must tolerate confidence=None end to end.
    from silk_render import build_view
    from silk_reports import render_docx

    _seed_funnel(db, product)
    _snapshot_with_saudi(db, product.hs_code)
    db.commit()

    from pathlib import Path

    view = build_view(build_engine_result(db, product))
    path = render_docx(view, str(tmp_path / "report.docx"))
    blob = Path(path or tmp_path / "report.docx").read_bytes()
    assert blob[:2] == b"PK"  # a real .docx (zip) came out

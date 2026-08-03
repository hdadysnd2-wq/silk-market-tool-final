"""The demo world_trade seed populates the funnel and demonstrates I9.

Makes `make dev` / `make demo` show a real "world screened → top 5": genuine
markets on top, transit hubs flagged and penalized (never silently topping on
re-export-inflated volume).
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import WorldTrade
from app.seeds.seed import seed_world_trade
from app.services.world_funnel import TRANSIT_HUB_TAG, screen_world


def test_seed_populates_world_trade(db):
    seed_world_trade(db)
    db.commit()
    assert db.scalar(select(func.count()).select_from(WorldTrade)) > 0


def test_seeded_funnel_demotes_transit_hubs(db):
    seed_world_trade(db)
    db.commit()

    result = screen_world(db, "392010")
    assert result.markets
    assert result.year == 2023  # decision #8 — the data year is present

    # A genuine market tops; no re-export hub silently on top (I9).
    assert result.markets[0].is_transit_hub is False

    hubs = [m for m in result.markets if m.is_transit_hub]
    assert hubs, "the demo data includes transit hubs"
    for h in hubs:
        assert TRANSIT_HUB_TAG in h.tags
        assert h.screen_score < float(h.import_usd)  # penalized


def test_seed_is_idempotent(db):
    seed_world_trade(db)
    db.commit()
    n1 = db.scalar(select(func.count()).select_from(WorldTrade))
    seed_world_trade(db)
    db.commit()
    n2 = db.scalar(select(func.count()).select_from(WorldTrade))
    assert n1 == n2

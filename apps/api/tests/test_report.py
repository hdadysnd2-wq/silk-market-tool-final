"""Product export-intelligence report: aggregation, JSON API, and HTML render."""

from __future__ import annotations

from app.services.buyer_discovery import discover_buyers
from app.services.competitor_snapshot import build_snapshot
from app.services.report import build_product_report


def _seed_pipeline(db, product, market_iso2="IN"):
    discover_buyers(db, product, market_iso2)
    build_snapshot(db, product.hs_code, market_iso2)
    db.commit()


def _seed_and_run_funnel(db, product):
    """Seed world_trade and run the world funnel so the product has an analysis."""
    from app.models import WorldTrade
    from app.services.ranking import run_product_world_analysis

    rows = [
        ("DEU", 700.0, False, False),  # genuine demand
        ("NLD", 1000.0, True, False),  # transit hub — highest raw volume
        ("IND", 500.0, False, True),  # mirror
    ]
    for iso3, usd, hub, mirror in rows:
        db.add(
            WorldTrade(
                hs6=product.hs_code,
                importer_iso3=iso3,
                year=2022,
                import_usd=usd,
                is_transit_hub=hub,
                is_mirror=mirror,
                source="UN Comtrade",
            )
        )
    db.commit()
    run_product_world_analysis(db, product)
    db.commit()


def test_report_aggregates_markets_buyers_and_snapshot(db, factory, product, market):
    _seed_pipeline(db, product)

    report = build_product_report(db, product, "en")

    assert report.factory.name_en == factory.name_en
    assert report.product.hs_code == product.hs_code
    assert report.summary.markets_analyzed == 1
    assert report.summary.total_buyers > 0
    assert report.summary.total_import_usd and report.summary.total_import_usd > 0

    ind = report.markets[0]
    assert ind.iso2 == "IN"
    assert ind.snapshot is not None
    assert ind.snapshot.top_exporters
    assert ind.top_buyers
    # Buyers are surfaced highest-score first.
    scores = [b.relevance_score for b in ind.top_buyers]
    assert scores == sorted(scores, reverse=True)


def test_report_without_analysis_is_empty_but_valid(db, factory, product):
    report = build_product_report(db, product, "en")
    assert report.summary.markets_analyzed == 0
    assert report.summary.total_buyers == 0
    assert report.summary.total_import_usd is None
    assert report.markets == []
    # No world analysis run yet → the funnel is a declared absence, not a stub.
    assert report.funnel is None


def test_report_includes_world_funnel(db, factory, product):
    _seed_and_run_funnel(db, product)

    report = build_product_report(db, product, "en")

    assert report.funnel is not None
    assert report.funnel.hs_code == product.hs_code
    top = report.funnel.top_markets
    assert top, "expected a funnel shortlist"
    # I9: the genuine market tops; the transit hub (highest raw volume) is demoted.
    assert top[0].importer_iso3 == "DEU"
    assert top[0].market_iso2 == "DE"  # alpha-3 → alpha-2 bridge surfaced
    assert top[0].year == 2022  # decision #8 — the data year travels with the figure
    nld = next(m for m in top if m.importer_iso3 == "NLD")
    assert nld.is_transit_hub is True
    assert nld.rank > top[0].rank


def test_report_html_includes_funnel(client, auth_headers, db, factory, product):
    _seed_and_run_funnel(db, product)

    res = client.get(f"/api/v1/products/{product.id}/report.html", headers=auth_headers)
    assert res.status_code == 200
    # The funnel's top market is rendered into the downloadable document.
    assert "World market funnel" in res.text
    assert "DEU" in res.text


def test_report_top_buyers_capped_per_market(db, factory, product, market, monkeypatch):
    from app.services import report as report_module

    monkeypatch.setattr(report_module, "TOP_BUYERS_PER_MARKET", 2)
    _seed_pipeline(db, product)

    section = build_product_report(db, product, "en").markets[0]
    assert len(section.top_buyers) <= 2
    # The full count is still reported even though only the top few are listed.
    assert section.buyer_count >= len(section.top_buyers)


def test_report_json_endpoint(client, auth_headers, db, factory, product, market):
    _seed_pipeline(db, product)

    res = client.get(f"/api/v1/products/{product.id}/report", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["product"]["hs_code"] == product.hs_code
    assert body["summary"]["markets_analyzed"] == 1
    assert body["markets"][0]["iso2"] == "IN"


def test_report_html_endpoint_is_self_contained(client, auth_headers, db, factory, product, market):
    _seed_pipeline(db, product)

    res = client.get(f"/api/v1/products/{product.id}/report.html", headers=auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    html = res.text
    assert "<!doctype html>" in html
    assert product.name_en in html
    assert factory.name_en in html
    # No external asset references — the document stands alone.
    assert "http://" not in html.split("<body")[0]


def test_report_html_arabic_is_rtl(client, auth_headers, db, factory, product, market):
    _seed_pipeline(db, product)

    res = client.get(f"/api/v1/products/{product.id}/report.html?locale=ar", headers=auth_headers)
    assert res.status_code == 200
    assert 'dir="rtl"' in res.text
    assert 'lang="ar"' in res.text
    assert product.name_ar in res.text


def test_report_requires_ownership(client, db, factory, product, market, admin_user):
    # A different factory's user may not read this product's report.
    from app.models import Factory, User, UserRole
    from app.security import create_access_token, hash_password

    other = Factory(name_ar="آخر", name_en="Other Factory")
    db.add(other)
    db.flush()
    intruder = User(
        email="intruder@other.test",
        password_hash=hash_password("Passw0rd!"),
        role=UserRole.factory_user,
        factory_id=other.id,
    )
    db.add(intruder)
    db.commit()
    token = create_access_token(intruder.id, intruder.role)

    res = client.get(
        f"/api/v1/products/{product.id}/report",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403

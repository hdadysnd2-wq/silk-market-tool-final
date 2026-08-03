"""The analysis API drives the world funnel over a confirmed product (I2 + I9)."""

from __future__ import annotations

from app.models import WorldTrade
from app.services.world_funnel import TRANSIT_HUB_TAG

HS6 = "392010"  # matches the confirmed hs_code on the `product` fixture
YEAR = 2022


def _seed_world(db, hs6=HS6):
    rows = [
        ("NLD", 1000.0, True, False),  # transit hub — highest raw volume
        ("DEU", 700.0, False, False),  # genuine demand
        ("IND", 500.0, False, True),  # mirror
        ("SGP", 400.0, True, False),  # transit hub
        ("XXX", None, False, False),  # no data
    ]
    for iso3, usd, hub, mirror in rows:
        db.add(
            WorldTrade(
                hs6=hs6,
                importer_iso3=iso3,
                year=YEAR,
                import_usd=usd,
                is_transit_hub=hub,
                is_mirror=mirror,
                source="UN Comtrade",
            )
        )
    db.commit()


def test_start_analysis_returns_transit_flagged_top5(client, db, product, auth_headers):
    _seed_world(db)

    resp = client.post(f"/api/v1/products/{product.id}/analysis", headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ranked"
    assert body["product_id"] == str(product.id)

    rankings = body["rankings"]
    assert rankings, "expected a ranked shortlist"
    # I9: the genuine market tops; the transit hub is demoted and flagged.
    assert rankings[0]["importer_iso3"] == "DEU"
    nld = next(r for r in rankings if r["importer_iso3"] == "NLD")
    assert nld["is_transit_hub"] is True
    assert TRANSIT_HUB_TAG in (nld["tags"] or [])
    assert nld["rank"] > rankings[0]["rank"]
    # Decision #8 — the data year travels with every figure.
    assert rankings[0]["year"] == YEAR


def test_analysis_blocked_until_hs_confirmed(client, db, factory, auth_headers):
    from app.models import Product

    unconfirmed = Product(
        factory_id=factory.id,
        name_ar="غير مؤكد",
        name_en="Unconfirmed Widget",
        currency="USD",
    )
    db.add(unconfirmed)
    db.commit()

    resp = client.post(f"/api/v1/products/{unconfirmed.id}/analysis", headers=auth_headers)
    assert resp.status_code == 409  # I2 — no world run on an unconfirmed HS code


def test_get_analysis_returns_rankings(client, db, product, auth_headers):
    _seed_world(db)
    created = client.post(f"/api/v1/products/{product.id}/analysis", headers=auth_headers).json()

    resp = client.get(f"/api/v1/analyses/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert {r["importer_iso3"] for r in resp.json()["rankings"]} == {
        "DEU",
        "IND",
        "NLD",
        "SGP",
        "XXX",
    }


def test_get_analysis_cross_factory_forbidden(client, db, product, auth_headers):
    from app.models import Factory, User, UserRole
    from app.security import create_access_token, hash_password

    _seed_world(db)
    created = client.post(f"/api/v1/products/{product.id}/analysis", headers=auth_headers).json()

    other_factory = Factory(name_ar="آخر", name_en="Other Factory")
    db.add(other_factory)
    db.flush()
    other_user = User(
        email="other-analysis@x.com",
        password_hash=hash_password("Passw0rd!"),
        role=UserRole.factory_user,
        factory_id=other_factory.id,
    )
    db.add(other_user)
    db.commit()

    token = create_access_token(other_user.id, other_user.role)
    resp = client.get(
        f"/api/v1/analyses/{created['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403

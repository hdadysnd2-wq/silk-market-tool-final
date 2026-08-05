"""Decision #6 / I8 — lead discovery is bound to a specific analysis.

The API refuses discovery for a product with no analysis, and every persisted
buyer match is stamped with the analysis id the fetch served.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Analysis, ProductBuyerMatch
from app.services.buyer_discovery import discover_buyers


def test_discover_refused_without_an_analysis(client, product, auth_headers):
    resp = client.post(
        f"/api/v1/products/{product.id}/discover",
        json={"markets": ["IN"]},
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "analysis" in resp.json()["detail"].lower()


def test_matches_are_stamped_with_the_analysis(client, db, product, market, auth_headers):
    analysis = Analysis(product_id=product.id, product_name=product.name_en, status="classified")
    db.add(analysis)
    db.commit()

    discover_buyers(db, product, "IN", analysis_id=analysis.id)
    db.commit()

    matches = db.scalars(
        select(ProductBuyerMatch).where(ProductBuyerMatch.product_id == product.id)
    ).all()
    assert matches, "discovery produced no matches"
    assert all(m.analysis_id == analysis.id for m in matches)

    # The binding is surfaced to the client on every lead row.
    res = client.get(f"/api/v1/products/{product.id}/buyers?market=IN", headers=auth_headers)
    assert res.status_code == 200, res.text
    rows = res.json()
    assert rows and all(r["analysis_id"] == str(analysis.id) for r in rows)

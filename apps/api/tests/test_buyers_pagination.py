"""Lock buyers-list pagination + single-query contacts (audit 2026-08-07 H2).

The buyers view is polled every few seconds and one market can hold ~220
buyers; the endpoint used to return the whole list and issue one contact query
per buyer. It now pages (bounded limit/offset) and batch-loads contacts.
"""

from __future__ import annotations

from app.models import ProductBuyerMatch
from tests.conftest import make_buyer_with_contact


def _seed_buyers(db, product, n: int) -> None:
    for i in range(n):
        _buyer, _contact = make_buyer_with_contact(
            db, email=f"c{i}@x.example.in", name=f"Buyer {i:03d}"
        )
        db.add(
            ProductBuyerMatch(
                product_id=product.id,
                buyer_id=_buyer.id,
                market_iso2="IN",
                relevance_score=1.0 - i / 1000.0,
            )
        )
    db.commit()


def test_default_page_is_bounded(client, db, product, auth_headers):
    _seed_buyers(db, product, 120)
    res = client.get(f"/api/v1/products/{product.id}/buyers?market=IN", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert len(res.json()) == 50  # default page, not all 120


def test_limit_and_offset_slice_deterministically(client, db, product, auth_headers):
    _seed_buyers(db, product, 30)
    base = f"/api/v1/products/{product.id}/buyers?market=IN"
    page1 = client.get(f"{base}&limit=10&offset=0", headers=auth_headers).json()
    page2 = client.get(f"{base}&limit=10&offset=10", headers=auth_headers).json()
    assert len(page1) == 10 and len(page2) == 10
    ids1 = {r["buyer"]["id"] for r in page1}
    ids2 = {r["buyer"]["id"] for r in page2}
    assert ids1.isdisjoint(ids2)  # no overlap between pages


def test_limit_is_clamped(client, db, product, auth_headers):
    _seed_buyers(db, product, 5)
    res = client.get(
        f"/api/v1/products/{product.id}/buyers?market=IN&limit=99999", headers=auth_headers
    )
    assert res.status_code == 200
    assert len(res.json()) == 5  # only 5 exist; clamp didn't error


def test_contacts_are_returned_for_the_page(client, db, product, auth_headers):
    _seed_buyers(db, product, 3)
    res = client.get(f"/api/v1/products/{product.id}/buyers?market=IN", headers=auth_headers)
    rows = res.json()
    assert all(len(r["contacts"]) == 1 for r in rows)

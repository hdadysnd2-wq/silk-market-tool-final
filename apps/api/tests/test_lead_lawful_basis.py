"""Per-lead lawful basis for direct marketing (I8 / PDPL Art. 25 / GDPR).

Every discovered lead records the lawful basis that established it: import history
on file → a prior commercial interaction (PDPL Art. 25 / GDPR legitimate interest);
a directory-only lead has none and is flagged for review. The basis is never
inflated beyond what discovery established.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import ProductBuyerMatch
from app.services.buyer_discovery import _lawful_basis, discover_buyers


def test_import_history_is_a_prior_interaction_basis():
    basis, note = _lawful_basis(
        shipments=[object()], evidence={"summary": "Imported 5 shipments of HS 392010"}
    )
    assert basis == "prior_import_activity"
    assert "PDPL Art. 25" in note
    assert "Imported 5 shipments" in note


def test_directory_only_lead_has_no_import_basis():
    basis, note = _lawful_basis(shipments=[], evidence={"summary": "directory"})
    assert basis == "directory_listing"
    assert "review" in note.lower()


def test_discovery_records_a_basis_on_every_lead(db, factory, product, market):
    discover_buyers(db, product, "IN")
    db.commit()

    matches = list(db.scalars(select(ProductBuyerMatch)))
    assert matches, "discovery created at least one lead"
    # Every lead carries a recorded basis + note (I8 — never left blank).
    assert all(m.lawful_basis for m in matches)
    assert all(m.basis_note for m in matches)
    # Customs-sourced leads (import history) carry the prior-interaction basis.
    assert any(m.lawful_basis == "prior_import_activity" for m in matches)


def test_buyers_listing_surfaces_the_lawful_basis(
    client, auth_headers, db, factory, product, market
):
    discover_buyers(db, product, "IN")
    db.commit()

    res = client.get(f"/api/v1/products/{product.id}/buyers?market=IN", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body
    for match in body:
        assert match["lawful_basis"]
        assert match["basis_note"]

"""HS classification is unified on the engine's single resolver (silk_hs_resolver).

After the unification there is exactly one HS classifier: product creation routes
through ``engine.resolve_hs_candidates`` (the name-based ``silk_hs_resolver``),
with the vision pass producing the description that feeds it. These tests pin the
observable contract of that path:

* classification only PROPOSES — ``product.hs_code`` stays uncommitted (I2);
* a resolver-proposed code is confirmable because the catalogue is lazily
  backfilled from the engine seed (no bulk-seeding of 5,600+ placeholder rows);
* a nonsense product declares a gap (``failed`` + empty candidates), never a
  fabricated code (I1).

They are hermetic: the mock LLM fills the vision description offline and the
resolver reads its bundled CSV seed — no network, no model key.
"""

from __future__ import annotations

from app.models import HSCode, Product
from app.services import hs_classifier

# A real product whose name resolves to a genuine HS6 (Natural honey, 040900),
# and a nonsense one that resolves to nothing.
_HONEY = {"name_ar": "عسل السدر", "name_en": "Sidr Honey"}
_NONSENSE = {"name_ar": "ززز", "name_en": "zzzqqxnonsense"}


def _create(client, auth_headers, spec: dict) -> dict:
    """POST a product (202 + pending) and return the classified product via GET.

    The intake pipeline is async: the POST is accepted with the product still
    ``pending``; under eager mode the task ran in-process during the POST, so a
    follow-up GET carries the classified result the client polls for.
    """
    res = client.post(
        "/api/v1/products",
        headers=auth_headers,
        data={**spec, "classify": "true"},
    )
    assert res.status_code == 202, res.text
    accepted = res.json()
    assert accepted["task_id"]
    assert accepted["product"]["classification_status"] == "pending"
    product_id = accepted["product"]["id"]
    got = client.get(f"/api/v1/products/{product_id}", headers=auth_headers)
    assert got.status_code == 200, got.text
    return got.json()


# -- (a) create → classified proposal, hs_code left uncommitted (I2) -----------


def test_create_product_classifies_via_resolver_without_committing(client, auth_headers):
    body = _create(client, auth_headers, _HONEY)

    assert body["classification_status"] == "classified"
    assert body["hs_candidates"], "resolver should propose at least one candidate"
    assert all(c["code"] for c in body["hs_candidates"])
    # I2: classification only proposes — the committed code stays uncommitted
    # until a human confirms, exactly like services.analysis.classify_and_persist.
    assert body["hs_code"] is None
    assert body["hs_confirmed_by_user"] is False


# -- (b) a resolver-proposed code is confirmable (catalogue backfill works) -----


def test_resolver_proposed_code_is_confirmable(client, auth_headers, db):
    created = _create(client, auth_headers, _HONEY)
    product_id = created["id"]
    chosen = created["hs_candidates"][0]["code"]

    # The resolver proposes real HS6 codes (e.g. 040900) that are NOT bulk-seeded
    # into the platform catalogue; classify backfilled it lazily, so confirming it
    # succeeds rather than 400-ing on an "unknown" code.
    res = client.put(
        f"/api/v1/products/{product_id}/hs-code",
        headers=auth_headers,
        json={"hs_code": chosen},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # I2: the committed code + the confirmed flag are set ONLY here, by confirm.
    assert body["hs_confirmed_by_user"] is True
    assert body["hs_code"] == chosen
    # The backfilled catalogue row is real and FK-valid.
    assert db.get(HSCode, chosen) is not None


# -- (c) nonsense → declared gap, never a fabricated code (I1) ------------------


def test_nonsense_product_declares_gap_not_a_fabricated_code(client, auth_headers):
    body = _create(client, auth_headers, _NONSENSE)

    assert body["classification_status"] == "failed"
    assert body["hs_candidates"] == []  # I1: no value ⇒ dropped, never invented
    assert body["hs_code"] is None


# -- service-level guards (no HTTP stack) --------------------------------------


def test_classify_product_proposes_without_setting_hs_code(db, factory):
    product = Product(
        factory_id=factory.id, name_ar="عسل السدر", name_en="Sidr Honey", currency="USD"
    )
    db.add(product)
    db.flush()

    candidates = hs_classifier.classify_product(db, product)

    assert candidates and all(c["code"] for c in candidates)
    assert product.classification_status == "classified"
    # I2: proposal only — classify never auto-commits or auto-confirms.
    assert product.hs_code is None
    assert product.hs_confirmed_by_user is False
    # Every proposed code was backfilled into the catalogue (FK/confirm-valid).
    assert db.get(HSCode, candidates[0]["code"]) is not None


def test_ensure_hs_code_backfills_real_codes_and_never_fabricates(db):
    # 040900 (Natural honey) is a real engine code that is not bulk-seeded here.
    assert db.get(HSCode, "040900") is None
    hs = hs_classifier.ensure_hs_code(db, "040900")
    assert hs is not None
    assert hs.code == "040900"
    assert hs.description_en  # populated from the engine seed
    assert hs.description_ar  # NOT NULL column always filled
    assert hs.level == 6
    # A code absent from the engine seed is a declared gap, never a fabricated row.
    assert hs_classifier.ensure_hs_code(db, "000000") is None

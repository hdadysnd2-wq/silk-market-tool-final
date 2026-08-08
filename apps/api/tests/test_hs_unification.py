"""HS classification is unified on the engine's single resolver (silk_hs_resolver).

After the unification there is exactly one HS classifier: product creation routes
through ``engine.resolve_hs_candidates`` (the name-based ``silk_hs_resolver``),
with the vision pass producing the description that feeds it. These tests pin the
observable contract of that path:

* an ambiguous result (``tier="candidates"``) only PROPOSES — ``product.hs_code``
  stays uncommitted until a human confirms (I2);
* the engine's STRICT ``tier="auto"`` verdict auto-commits the code, tagged
  ``hs_auto_classified`` — never over a human confirmation, and never when
  label signals exist that the engine could not consult (ADR-0009 + lesson 79);
* a human confirm/override stays supreme: it is the only writer of
  ``hs_confirmed_by_user``, clears the auto tag, and logs an override;
* a resolver-proposed code is confirmable because the catalogue is lazily
  backfilled from the engine seed (no bulk-seeding of 5,600+ placeholder rows);
* a nonsense product declares a gap (``failed`` + empty candidates), never a
  fabricated code (I1).

They are hermetic: the mock LLM fills the vision description offline and the
resolver reads its bundled CSV seed — no network, no model key.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import HSCode, HSCorrection, Product
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
    """Ambiguous tier ("Sidr Honey" scores below the engine's strict auto gate)
    → proposal only, exactly as before ADR-0009."""
    product = Product(
        factory_id=factory.id, name_ar="عسل السدر", name_en="Sidr Honey", currency="USD"
    )
    db.add(product)
    db.flush()

    candidates = hs_classifier.classify_product(db, product)

    assert candidates and all(c["code"] for c in candidates)
    assert product.classification_status == "classified"
    # I2: on an unclear verdict classify never commits or confirms.
    assert product.hs_code is None
    assert product.hs_confirmed_by_user is False
    assert product.hs_auto_classified is False
    # Every proposed code was backfilled into the catalogue (FK/confirm-valid).
    assert db.get(HSCode, candidates[0]["code"]) is not None


# -- (e) ADR-0009: the STRICT auto tier commits, provenance-tagged --------------


def test_classify_product_auto_commits_on_strict_auto_tier(db, factory):
    """ "Dates تمور" passes the engine's strict auto gate (verified, overlap ≥ 0.8,
    clear margin) → the code IS committed, tagged auto, human flag untouched."""
    product = Product(factory_id=factory.id, name_ar="تمور", name_en="Dates", currency="USD")
    db.add(product)
    db.flush()

    hs_classifier.classify_product(db, product)

    assert product.hs_code == "080410"
    assert product.hs_auto_classified is True
    # hs_confirmed_by_user stays HUMAN-ONLY (I2): auto commit never fakes it.
    assert product.hs_confirmed_by_user is False
    # The committed code is FK-valid (catalogue backfilled before commit).
    assert db.get(HSCode, "080410") is not None


def test_auto_commit_never_overwrites_human_confirmed(db, factory):
    """Human supremacy: re-classifying a human-confirmed product proposes fresh
    candidates but NEVER touches the confirmed code."""
    hs_classifier.ensure_hs_code(db, "040900")
    product = Product(
        factory_id=factory.id,
        name_ar="تمور",
        name_en="Dates",
        currency="USD",
        hs_code="040900",  # deliberately "wrong" — but human-confirmed
        hs_confirmed_by_user=True,
    )
    db.add(product)
    db.flush()

    hs_classifier.classify_product(db, product)

    assert product.hs_code == "040900"  # untouched
    assert product.hs_confirmed_by_user is True
    assert product.hs_auto_classified is False


def test_confirm_clears_auto_flag_and_records_override(db, factory):
    """A human override of an auto-committed code clears the auto tag and logs
    an HSCorrection with the machine's code as `suggested` (classifier feedback)."""
    product = Product(factory_id=factory.id, name_ar="تمور", name_en="Dates", currency="USD")
    db.add(product)
    db.flush()
    hs_classifier.classify_product(db, product)
    assert product.hs_auto_classified is True and product.hs_code == "080410"

    hs_classifier.confirm_hs_code(db, product, "040900", None)

    assert product.hs_code == "040900"
    assert product.hs_confirmed_by_user is True
    assert product.hs_auto_classified is False  # human decision superseded it
    correction = db.scalars(select(HSCorrection).where(HSCorrection.product_id == product.id)).one()
    assert correction.suggested_code == "080410"
    assert correction.chosen_code == "040900"


def test_auto_committed_code_opens_downstream_gates(client, auth_headers, db, factory):
    """ADR-0009 end-to-end: a strict-auto committed code passes the analysis
    gate exactly like a human-confirmed one (the gate predicate is hs_ready) —
    while an uncommitted candidates-tier product still 409s.

    The auto-committed state is constructed directly: through the full hermetic
    intake the mock vision fills attributes, and the engine (lesson 79)
    rightly refuses `tier="auto"` when those label signals cannot be consulted
    offline — the commit path itself is covered by the service-level test on an
    attribute-free product."""
    hs_classifier.ensure_hs_code(db, "080410")
    dates = Product(
        factory_id=factory.id,
        name_ar="تمور",
        name_en="Dates",
        currency="USD",
        hs_code="080410",
        hs_auto_classified=True,  # machine-committed; NOT human-confirmed
        classification_status="classified",
    )
    db.add(dates)
    db.commit()
    res = client.post(f"/api/v1/products/{dates.id}/analysis", headers=auth_headers)
    assert res.status_code == 202, res.text

    honey = _create(client, auth_headers, _HONEY)
    assert honey["hs_code"] is None  # candidates tier — uncommitted
    res = client.post(f"/api/v1/products/{honey['id']}/analysis", headers=auth_headers)
    assert res.status_code == 409, res.text


def test_label_signals_without_llm_never_auto_commit(db, factory):
    """Lesson 79 at the platform seam: vision attributes (label signals) present
    but the engine could not consult the LLM offline → the engine downgrades
    auto → candidates, so nothing is committed. The strawberry-milk incident can
    never be auto-committed from name-only evidence."""
    product = Product(
        factory_id=factory.id,
        name_ar="حليب",
        name_en="milk",
        currency="USD",
        attributes=[
            {"name": "flavor", "value": "Strawberry (حليب بالفراولة)"},
            {"name": "nutrition", "value": "Sugars 11g"},
        ],
    )
    db.add(product)
    db.flush()

    candidates = hs_classifier.classify_product(db, product)

    assert candidates, "downgrade must keep candidates for the human picker"
    assert product.hs_code is None
    assert product.hs_auto_classified is False
    assert product.hs_confirmed_by_user is False


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

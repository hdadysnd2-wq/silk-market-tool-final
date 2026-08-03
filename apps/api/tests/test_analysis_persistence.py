"""An analysis runs through the engine and persists to Postgres with provenance.

Phase 1 acceptance slice: the engine's HS proposals are persisted as an
``Analysis`` + ``HSClassification`` rows, each carrying its full provenance
envelope (I1), stored unconfirmed (I2), with the deepen intent recorded (I5).
The service is exercised directly with the test session — the same pattern the
rest of the suite uses for Celery-task logic.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Analysis, HSClassification, Product
from app.services.analysis import classify_and_persist


def _product(db, factory, name_en="honey", name_ar="عسل") -> Product:
    p = Product(factory_id=factory.id, name_ar=name_ar, name_en=name_en, currency="USD")
    db.add(p)
    db.commit()
    return p


def test_classify_and_persist_writes_analysis_with_provenance(db, factory):
    product = _product(db, factory)

    analysis = classify_and_persist(db, product, deepen=False)
    db.commit()

    stored = db.get(Analysis, analysis.id)
    assert stored is not None
    assert stored.product_id == product.id
    assert stored.product_name == "honey"
    assert stored.status == "classified"  # "honey" resolves to a real HS6
    assert stored.deepen is False

    rows = list(
        db.scalars(
            select(HSClassification)
            .where(HSClassification.analysis_id == analysis.id)
            .order_by(HSClassification.rank)
        )
    )
    assert rows, "expected at least one persisted HS proposal"
    top = rows[0]
    assert top.rank == 1
    assert top.proposed_code is not None  # a real code, not a fabricated gap
    assert top.provider == "silk_hs_resolver"  # provenance survives to the DB
    assert top.source  # non-empty source label
    assert float(top.confidence) > 0.0
    # I2: proposals are stored unconfirmed — never an auto-committed declaration.
    assert all(r.is_confirmed is False for r in rows)
    # The product's committed HS code is untouched by a proposal run.
    assert product.hs_code is None


def test_no_match_persists_declared_gap_not_a_fabricated_code(db, factory):
    # A nonsense name yields no real HS match; the run is recorded as failed and
    # any persisted proposal carries value=None (I1 — never a guessed code).
    product = _product(db, factory, name_en="zzzqqxnonsense", name_ar="ززز")

    analysis = classify_and_persist(db, product, deepen=False)
    db.commit()

    assert analysis.status == "failed"
    rows = list(
        db.scalars(select(HSClassification).where(HSClassification.analysis_id == analysis.id))
    )
    # Whatever was written declares a gap rather than inventing a code.
    assert all(r.proposed_code is None for r in rows)


def test_deepen_flag_is_recorded_on_the_analysis(db, factory):
    product = _product(db, factory)
    analysis = classify_and_persist(db, product, deepen=True)
    db.commit()
    assert db.get(Analysis, analysis.id).deepen is True

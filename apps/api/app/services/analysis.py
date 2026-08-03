"""Analysis persistence: run the engine's HS classifier and store it (I1, I2, I5).

Called by the Celery ``run_hs_analysis`` task (which owns the session scope) and,
in tests, directly with a session — the same pattern the rest of the suite uses.
Every proposal is persisted with its full provenance envelope; nothing is
auto-confirmed.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Analysis, HSClassification, Product
from app.services import engine

log = get_logger(__name__)


def classify_and_persist(db: Session, product: Product, deepen: bool = False) -> Analysis:
    """Resolve HS6 proposals for ``product`` via the engine and persist them.

    Creates one ``Analysis`` row and one ``HSClassification`` per ranked candidate,
    each carrying its provenance envelope. Proposals are stored **unconfirmed**
    (I2). The engine call runs inside the re-established ``/deepen`` scope (I5).
    The product's committed ``hs_code`` is left untouched — confirmation is a
    separate, human-driven step.
    """
    name = product.name_en or product.name_ar
    with engine.deepen_scope(deepen):
        candidates = engine.resolve_hs_candidates(name)

    # A candidate with a real code is a genuine proposal; a value=None candidate
    # is a declared gap (I1) and does not make the run "classified".
    has_match = any(c.value is not None for c in candidates)
    analysis = Analysis(
        product_id=product.id,
        product_name=name,
        status="classified" if has_match else "failed",
        deepen=deepen,
    )
    db.add(analysis)
    db.flush()

    for rank, c in enumerate(candidates, start=1):
        db.add(
            HSClassification(
                analysis_id=analysis.id,
                rank=rank,
                proposed_code=c.value,
                confidence=c.confidence,
                source=c.source,
                provider=c.provider,
                data_year=c.data_year,
                note=c.note,
                is_confirmed=False,
            )
        )
    db.flush()
    log.info(
        "analysis_hs_classified",
        analysis_id=str(analysis.id),
        product_id=str(product.id),
        deepen=deepen,
        proposals=[c.value for c in candidates],
    )
    return analysis

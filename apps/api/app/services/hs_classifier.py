"""Product → HS6 classification via the engine's single resolver (``silk_hs_resolver``).

The platform keeps NO parallel HS logic: every proposal comes from the engine's
name-based classifier through :func:`app.services.engine.resolve_hs_candidates`
(one classifier only). This service only shapes the engine's provenance envelopes
into ``product.hs_candidates`` and lazily backfills the HS catalogue so a
resolver-proposed code stays foreign-key-valid and confirmable. It PROPOSES only:
the committed ``product.hs_code`` + ``hs_confirmed_by_user`` are set solely in
:func:`confirm_hs_code` (invariant I2). A ``value=None`` resolve is a declared gap
and is dropped, never invented (invariant I1).
"""

from __future__ import annotations

import csv
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import HSCode, HSCorrection, Product

log = get_logger(__name__)

#: Lazily-parsed ``{hs_code: row}`` view of the engine's HS seed CSV, used to
#: backfill the platform catalogue on demand (see :func:`ensure_hs_code`). Parsed
#: once on first use and cached for the process lifetime.
_ENGINE_HS_ROWS: dict[str, dict[str, str]] | None = None


def _engine_hs_rows() -> dict[str, dict[str, str]]:
    """Parse (once) the engine's HS seed CSV into a ``{code: row}`` lookup.

    The CSV is located relative to the resolver module so the two never drift.
    A missing/unreadable seed degrades to an empty map (a declared gap, not a
    crash) — ``ensure_hs_code`` then simply cannot backfill.
    """
    global _ENGINE_HS_ROWS
    if _ENGINE_HS_ROWS is None:
        import silk_hs_resolver

        csv_path = Path(silk_hs_resolver.__file__).parent / "data" / "hs_codes.csv"
        rows: dict[str, dict[str, str]] = {}
        try:
            with csv_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    code = (row.get("hs_code") or "").strip()
                    if code:
                        rows[code] = row
        except OSError as exc:  # missing/unreadable seed → empty (declared gap)
            log.warning("hs_seed_csv_unreadable", path=str(csv_path), error=str(exc))
        _ENGINE_HS_ROWS = rows
    return _ENGINE_HS_ROWS


def ensure_hs_code(db: Session, code: str) -> HSCode | None:
    """Return the catalogue row for ``code``, backfilling it from the engine seed.

    The engine resolver proposes real international HS6 codes that may not be in
    the platform's curated ``hs_codes`` table. Rather than bulk-seed 5,600+
    placeholder rows, we lazily upsert exactly the code a proposal (or a human
    confirmation) needs, so ``product.hs_code``'s foreign key stays valid. A code
    absent from the engine seed returns ``None`` (never a fabricated row, I1).
    """
    existing = db.get(HSCode, code)
    if existing is not None:
        return existing
    row = _engine_hs_rows().get(code)
    if row is None:
        return None
    name_en = (row.get("name_en") or "").strip()
    name_ar = (row.get("name_ar") or "").strip()
    hs = HSCode(
        code=code,
        description_en=name_en,
        # The seed leaves most name_ar blank; fall back to the English name so the
        # NOT NULL column always holds a real description, never an empty string.
        description_ar=name_ar or name_en,
        level=len(code) if len(code) in {2, 4, 6} else 6,
    )
    db.add(hs)
    db.flush()
    return hs


def classify_product(db: Session, product: Product) -> list[dict]:
    """Propose up to three HS6 candidates for ``product`` via the engine (I1, I2).

    The query is the product name enriched with the vision description for extra
    keyword signal (name first). If that enriched query confirms nothing, it falls
    back to the bare name — the resolver's confirmation gate penalises unrelated
    description terms, so a good name match must not be lost to descriptive noise.
    Every candidate is an engine ``DataContract`` with a real code; a ``value=None``
    envelope is a declared gap and is dropped, never invented. This only PROPOSES:
    ``product.hs_code`` is never set here (I2 — committed solely by
    :func:`confirm_hs_code`), mirroring ``services.analysis.classify_and_persist``.
    """
    from app.services import engine

    name_parts = [product.name_en, product.name_ar]
    enriched = [*name_parts, product.description_en, product.description_ar]
    query = " ".join(part for part in enriched if part)
    contracts = engine.resolve_hs_candidates(query)
    if not any(c.value is not None for c in contracts):
        name_query = " ".join(part for part in name_parts if part)
        if name_query and name_query != query:
            contracts = engine.resolve_hs_candidates(name_query)

    candidates: list[dict] = []
    for c in contracts:
        if c.value is None:
            continue
        known = ensure_hs_code(db, c.value)
        candidates.append(
            {
                "code": c.value,
                "confidence": round(c.confidence, 3),
                "rationale": c.note,
                "description_en": known.description_en if known else None,
                "description_ar": known.description_ar if known else None,
                "in_catalogue": known is not None,
            }
        )

    product.hs_candidates = candidates
    product.classification_status = "classified" if candidates else "failed"
    db.flush()
    log.info(
        "product_classified",
        product_id=str(product.id),
        provider="silk_hs_resolver",
        status=product.classification_status,
        candidates=[c["code"] for c in candidates],
    )
    return candidates


def confirm_hs_code(
    db: Session,
    product: Product,
    chosen_code: str,
    user_id: uuid.UUID | None,
) -> Product:
    """Record the user's HS choice, logging an override for classifier feedback.

    Backfills the catalogue first (:func:`ensure_hs_code`) so a human can confirm
    any real engine code even if it was never seeded — the committed ``hs_code``
    FK stays valid. This is the ONLY place ``product.hs_code`` +
    ``hs_confirmed_by_user`` are set (invariant I2).
    """
    ensure_hs_code(db, chosen_code)

    suggested = product.hs_candidates[0] if product.hs_candidates else None
    suggested_code = suggested["code"] if suggested else None

    if suggested_code and suggested_code != chosen_code:
        db.add(
            HSCorrection(
                product_id=product.id,
                suggested_code=suggested_code,
                suggested_confidence=suggested["confidence"] if suggested else None,
                chosen_code=chosen_code,
                corrected_by=user_id,
            )
        )
        log.info(
            "hs_code_overridden",
            product_id=str(product.id),
            suggested=suggested_code,
            chosen=chosen_code,
        )

    product.hs_code = chosen_code
    product.hs_confirmed_by_user = True
    db.flush()
    return product

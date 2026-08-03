"""Product → HS6 classification via the (real or mock) vision LLM."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import HSCode, HSCorrection, Product
from app.providers.base import LLMProvider
from app.providers.llm.prompts import (
    HS_CLASSIFICATION_SCHEMA,
    HS_SYSTEM_PROMPT,
    hs_user_prompt,
)

log = get_logger(__name__)


def classify_product(db: Session, product: Product, llm: LLMProvider) -> list[dict]:
    """Populate ``product.hs_candidates`` with up to three HS6 suggestions."""
    image_bytes = _load_image(product)
    prompt = hs_user_prompt(
        name=product.name_en or product.name_ar,
        description=product.description_en or product.description_ar,
        sector=None,
        has_image=image_bytes is not None,
    )

    response = llm.complete_with_image(
        system=HS_SYSTEM_PROMPT,
        prompt=prompt,
        image_bytes=image_bytes,
        json_schema=HS_CLASSIFICATION_SCHEMA,
    )
    candidates = _validate(db, (response.parsed or {}).get("candidates", []))

    product.hs_candidates = candidates
    product.classification_status = "classified" if candidates else "failed"
    # Pre-fill the best candidate; the user still confirms or overrides.
    if candidates and not product.hs_confirmed_by_user:
        product.hs_code = candidates[0]["code"]
    db.flush()
    log.info(
        "product_classified",
        product_id=str(product.id),
        provider=response.provider_name,
        candidates=[c["code"] for c in candidates],
    )
    return candidates


def _load_image(product: Product) -> bytes | None:
    if not product.image_url:
        return None
    if product.image_url.startswith("file://"):
        from pathlib import Path

        path = Path(product.image_url[len("file://") :])
        if path.exists():
            return path.read_bytes()
    # Remote (S3/presigned) images are handed to the real LLM by URL in a fuller
    # build; the mock classifier reads the text prompt, so a missing byte payload
    # is fine here.
    return None


def _validate(db: Session, raw_candidates: list[dict]) -> list[dict]:
    """Keep only well-formed candidates whose codes exist in the HS catalogue."""
    valid: list[dict] = []
    seen: set[str] = set()
    for item in raw_candidates[:3]:
        code = str(item.get("code", "")).strip()
        if not code or code in seen:
            continue
        known = db.get(HSCode, code)
        seen.add(code)
        if known is None:
            # Drop hallucinated / out-of-catalogue codes: an HS code that maps to
            # nothing must never become product.hs_code and drive discovery.
            log.info("hs_candidate_rejected_not_in_catalogue", code=code)
            continue
        valid.append(
            {
                "code": code,
                "confidence": round(float(item.get("confidence", 0.0)), 3),
                "rationale": item.get("rationale", ""),
                "description_en": known.description_en,
                "description_ar": known.description_ar,
                "in_catalogue": True,
            }
        )
    return valid


def confirm_hs_code(
    db: Session,
    product: Product,
    chosen_code: str,
    user_id: uuid.UUID | None,
) -> Product:
    """Record the user's HS choice, logging an override for classifier feedback."""
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

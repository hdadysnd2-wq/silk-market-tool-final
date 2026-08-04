"""Visual product understanding (DoD step 1): image → AR/EN description + attributes.

The same vision adapter that proposes an HS code also describes the product for the
export catalogue. It runs deterministically on the mock offline and on the real
Anthropic vision adapter once keyed. It never overwrites a description the factory
typed itself — it only fills what is missing; extracted attributes are additive.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Product
from app.providers.base import LLMProvider
from app.providers.llm.prompts import (
    PRODUCT_VISION_SCHEMA,
    PRODUCT_VISION_SYSTEM_PROMPT,
    product_vision_prompt,
)
from app.services.hs_classifier import _load_image

log = get_logger(__name__)


def describe_product(db: Session, product: Product, llm: LLMProvider) -> dict[str, Any]:
    """Fill the product's AR/EN description (if missing) and attributes from vision."""
    image_bytes = _load_image(product)
    prompt = product_vision_prompt(
        name=product.name_en or product.name_ar,
        description=product.description_en or product.description_ar,
        has_image=image_bytes is not None,
    )
    response = llm.complete_with_image(
        system=PRODUCT_VISION_SYSTEM_PROMPT,
        prompt=prompt,
        image_bytes=image_bytes,
        json_schema=PRODUCT_VISION_SCHEMA,
    )
    parsed = response.parsed or {}

    # Never overwrite a description the factory wrote — only fill what is missing.
    if not product.description_en and parsed.get("description_en"):
        product.description_en = parsed["description_en"]
    if not product.description_ar and parsed.get("description_ar"):
        product.description_ar = parsed["description_ar"]
    attributes = parsed.get("attributes") or None
    if attributes:
        product.attributes = attributes
    db.flush()
    log.info(
        "product_described",
        product_id=str(product.id),
        provider=response.provider_name,
        attributes=len(attributes or []),
    )
    return parsed

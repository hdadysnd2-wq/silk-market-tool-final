from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class HSCandidate(BaseModel):
    code: str
    confidence: float
    rationale: str | None = None
    description_en: str | None = None
    description_ar: str | None = None
    in_catalogue: bool = True


class ProductOut(BaseModel):
    id: uuid.UUID
    factory_id: uuid.UUID
    name_ar: str
    name_en: str
    description_ar: str | None
    description_en: str | None
    #: Salient visual attributes from the vision pass ([{name, value}, …]).
    attributes: list[dict] | None = None
    image_url: str | None
    price_min: float | None
    price_max: float | None
    #: Real factory-declared per-unit cost (in ``currency``); null when not supplied.
    cost_per_unit: float | None = None
    currency: str
    hs_code: str | None
    hs_candidates: list[HSCandidate] | None
    hs_confirmed_by_user: bool
    classification_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductAccepted(BaseModel):
    """202 envelope for the async intake pipeline: the enqueued task + the product.

    The product is reported as it was *accepted* (``classification_status`` still
    ``pending``); the client polls ``GET /products/{id}`` for the classified result
    once the worker finishes.
    """

    task_id: str
    product: ProductOut


class HSConfirmRequest(BaseModel):
    hs_code: str = Field(min_length=2, max_length=6)


class HSCodeOut(BaseModel):
    code: str
    level: int
    description_en: str
    description_ar: str
    sector: str | None

    model_config = {"from_attributes": True}

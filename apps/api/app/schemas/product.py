from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name_ar: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)
    description_ar: str | None = None
    description_en: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str = "USD"


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
    image_url: str | None
    price_min: float | None
    price_max: float | None
    currency: str
    hs_code: str | None
    hs_candidates: list[HSCandidate] | None
    hs_confirmed_by_user: bool
    classification_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HSConfirmRequest(BaseModel):
    hs_code: str = Field(min_length=2, max_length=6)


class HSCodeOut(BaseModel):
    code: str
    level: int
    description_en: str
    description_ar: str
    sector: str | None

    model_config = {"from_attributes": True}

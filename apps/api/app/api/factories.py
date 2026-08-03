"""Factory profile and deliverability settings for the current tenant."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbDep, resolve_factory
from app.models import utcnow
from app.schemas.common import DeliverabilityUpdate, FactoryOut, FactoryUpdate
from app.security import CurrentUser

router = APIRouter(prefix="/factory", tags=["factory"])


@router.get("", response_model=FactoryOut)
def get_my_factory(db: DbDep, user: CurrentUser) -> FactoryOut:
    return FactoryOut.model_validate(resolve_factory(db, user))


@router.put("", response_model=FactoryOut)
def update_my_factory(payload: FactoryUpdate, db: DbDep, user: CurrentUser) -> FactoryOut:
    factory = resolve_factory(db, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(factory, field, value)
    db.commit()
    return FactoryOut.model_validate(factory)


@router.put("/deliverability", response_model=FactoryOut)
def update_deliverability(
    payload: DeliverabilityUpdate, db: DbDep, user: CurrentUser
) -> FactoryOut:
    factory = resolve_factory(db, user)
    data = payload.model_dump(exclude_unset=True)
    if data.pop("start_warmup", None):
        factory.warmup_started_at = factory.warmup_started_at or utcnow()
        factory.warmup_day = max(factory.warmup_day, 1)
    for field, value in data.items():
        setattr(factory, field, value)
    db.commit()
    return FactoryOut.model_validate(factory)

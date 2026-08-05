"""Factory profile and deliverability settings for the current tenant."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbDep, resolve_factory
from app.config import get_settings
from app.models import utcnow
from app.schemas.common import DeliverabilityUpdate, DnsCheckOut, FactoryOut, FactoryUpdate
from app.security import CurrentUser
from app.services import audit, dns_check

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


@router.post("/deliverability/check", response_model=DnsCheckOut)
def check_deliverability_dns(db: DbDep, user: CurrentUser) -> DnsCheckOut:
    """Resolve the sending domain's SPF/DKIM/DMARC and record the verified state.

    This is the ONLY path that flips spf_ok/dkim_ok/dmarc_ok — tenants cannot
    self-attest them (the PUT schemas dropped those fields). Results are written
    to the factory and an audit row so the check is traceable.
    """
    factory = resolve_factory(db, user)
    if not factory.sending_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set a sending domain before running the deliverability check.",
        )

    selectors = tuple(s.strip() for s in get_settings().dkim_selectors.split(",") if s.strip()) or (
        "default",
    )
    result = dns_check.check_deliverability(factory.sending_domain, dkim_selectors=selectors)

    factory.spf_ok = result.spf_ok
    factory.dkim_ok = result.dkim_ok
    factory.dmarc_ok = result.dmarc_ok
    audit.record(
        db,
        action="factory.dns_checked",
        entity_type="factory",
        entity_id=factory.id,
        actor=user,
        payload={
            "domain": factory.sending_domain,
            "spf_ok": result.spf_ok,
            "dkim_ok": result.dkim_ok,
            "dmarc_ok": result.dmarc_ok,
        },
    )
    db.commit()
    return DnsCheckOut(
        spf_ok=result.spf_ok,
        dkim_ok=result.dkim_ok,
        dmarc_ok=result.dmarc_ok,
        notes=result.notes,
    )

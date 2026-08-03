"""Buyer discovery pipeline.

For one product in one market: pull transaction-level importers (customs), add
long-tail candidates (Maps), deduplicate against existing buyers, enrich
firmographics, find and verify contacts, then score every match. Each step is
idempotent so re-running discovery refreshes rather than duplicates.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import (
    Buyer,
    BuyerSource,
    Contact,
    Market,
    Product,
    ProductBuyerMatch,
    Shipment,
    VerificationStatus,
    utcnow,
)
from app.providers.base import SourceType
from app.providers.countries import primary_language
from app.providers.registry import (
    get_email_waterfall,
    get_enrichment_provider,
    get_maps_provider,
    get_shipments_provider,
)
from app.services import normalization
from app.services.scoring import ScoringInput, score_buyer

log = get_logger(__name__)

_SEARCH_TERMS = {
    "39": "plastics packaging distributor importer",
    "08": "dates dried fruit importer distributor",
    "17": "confectionery sweets importer distributor",
    "19": "bakery biscuits importer distributor",
    "20": "food preserves importer distributor",
    "04": "dairy foods importer distributor",
}


def discover_buyers(db: Session, product: Product, market_iso2: str) -> dict:
    """Run the full pipeline; return a small summary for logging/telemetry."""
    if not product.hs_code:
        raise ValueError("Product must be classified before discovery")

    market = db.get(Market, market_iso2)
    if market is None:
        raise ValueError(f"Unknown market {market_iso2}")

    hs_code = product.hs_code
    settings_providers = {
        "shipments": get_shipments_provider(),
        "maps": get_maps_provider(),
        "enrichment": get_enrichment_provider(),
        "waterfall": get_email_waterfall(),
    }

    # Existing buyers in this country, for dedup.
    existing_rows = db.scalars(select(Buyer).where(Buyer.country_iso2 == market_iso2)).all()
    existing_index = {b.normalized_name: b for b in existing_rows}

    # --- 1. Customs importers (transaction-level, strongest intent) ----------
    shipment_records = settings_providers["shipments"].importer_shipments(
        hs_code, market_iso2, limit=200
    )
    grouped: dict[str, list] = defaultdict(list)
    for rec in shipment_records:
        grouped[rec.data.consignee_name].append(rec)

    discovered = 0
    for name, records in grouped.items():
        buyer = _upsert_buyer(
            db,
            existing_index,
            name,
            market_iso2,
            BuyerSource.customs,
            confidence=records[0].confidence,
        )
        _store_shipments(db, buyer, records)
        discovered += 1

    # --- 2. Maps long-tail (supplementary, flagged for legal review) ---------
    term = _SEARCH_TERMS.get(hs_code[:2], "importer distributor")
    for rec in settings_providers["maps"].search_importers(term, market_iso2, limit=20):
        buyer = _upsert_buyer(
            db,
            existing_index,
            rec.data.name,
            market_iso2,
            BuyerSource.maps,
            confidence=rec.confidence,
        )
        buyer.legal_review_required = True
        if rec.data.website and not buyer.website:
            buyer.website = rec.data.website
            buyer.domain = buyer.domain or _domain_from_url(rec.data.website)
        if rec.data.phone and not buyer.phone:
            buyer.phone = rec.data.phone
        if rec.data.address and not buyer.address:
            buyer.address = rec.data.address

    db.flush()

    # --- 3. Enrichment + contacts + scoring per buyer ------------------------
    buyers = db.scalars(select(Buyer).where(Buyer.country_iso2 == market_iso2)).all()
    scored = 0
    for buyer in buyers:
        _enrich(db, buyer, settings_providers["enrichment"])
        _find_contacts(db, buyer, settings_providers["waterfall"])
        _score(db, product, buyer, market_iso2)
        scored += 1

    db.flush()
    summary = {
        "product_id": str(product.id),
        "market": market_iso2,
        "discovered": discovered,
        "scored": scored,
    }
    log.info("discovery_complete", **summary)
    return summary


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------


def _upsert_buyer(
    db: Session,
    index: dict[str, Buyer],
    name: str,
    market_iso2: str,
    source: BuyerSource,
    confidence: float,
) -> Buyer:
    norm = normalization.normalize_name(name)
    dup_key = normalization.find_duplicate(name, {k: k for k in index})
    if dup_key and dup_key in index:
        return index[dup_key]

    buyer = Buyer(
        name=name,
        normalized_name=norm,
        country_iso2=market_iso2,
        source=source,
        source_confidence=confidence,
        freshness_at=utcnow(),
    )
    db.add(buyer)
    db.flush()
    index[norm] = buyer
    return buyer


def _store_shipments(db: Session, buyer: Buyer, records: list) -> None:
    existing = db.scalar(select(Shipment).where(Shipment.buyer_id == buyer.id).limit(1))
    if existing is not None:
        return  # shipments already ingested for this buyer
    for rec in records:
        data = rec.data
        db.add(
            Shipment(
                buyer_id=buyer.id,
                raw_consignee_name=data.consignee_name,
                raw_shipper_name=data.shipper_name,
                hs_code=data.hs_code,
                origin_iso2=data.origin_iso2,
                dest_iso2=data.dest_iso2,
                shipment_date=data.shipment_date,
                value_usd=data.value_usd,
                quantity=data.quantity,
                quantity_unit=data.quantity_unit,
                source=BuyerSource.customs,
                provider_name=rec.provider_name,
                source_confidence=rec.confidence,
            )
        )


def _enrich(db: Session, buyer: Buyer, provider) -> None:
    if buyer.enriched_at is not None:
        return
    record = provider.enrich_company(buyer.name, buyer.country_iso2, buyer.domain)
    if record is None:
        buyer.enriched_at = utcnow()
        return
    firmo = record.data
    buyer.domain = buyer.domain or firmo.domain
    buyer.website = buyer.website or firmo.website
    buyer.industry = buyer.industry or firmo.industry
    buyer.employee_count = buyer.employee_count or firmo.employee_count
    buyer.city = buyer.city or firmo.city
    buyer.firmographics = {
        "revenue_band": firmo.revenue_band,
        "key_people": firmo.key_people,
        "provider": record.provider_name,
    }
    buyer.enriched_at = utcnow()
    db.flush()


def _find_contacts(db: Session, buyer: Buyer, waterfall) -> None:
    has_contact = db.scalar(select(Contact).where(Contact.buyer_id == buyer.id).limit(1))
    if has_contact is not None:
        return
    language = primary_language(buyer.country_iso2)
    for entry in waterfall.resolve(buyer.name, buyer.domain, buyer.country_iso2):
        db.add(
            Contact(
                buyer_id=buyer.id,
                email=entry["email"].lower(),
                full_name=entry.get("full_name"),
                title=entry.get("title"),
                language=language,
                verification_status=VerificationStatus(entry["verification_status"]),
                verified_at=utcnow(),
                source=entry.get("source"),
                found_via=entry.get("found_via"),
                confidence=entry.get("confidence", 0.5),
            )
        )
    db.flush()


def _score(db: Session, product: Product, buyer: Buyer, market_iso2: str) -> None:
    shipments = db.scalars(select(Shipment).where(Shipment.buyer_id == buyer.id)).all()

    today = utcnow().date()
    recent = [s for s in shipments if 0 <= (today - s.shipment_date).days <= 365]
    total_value = sum(float(s.value_usd or 0) for s in recent)
    buyer_hs = sorted({s.hs_code for s in shipments}) or [product.hs_code]
    last_days = (
        max(0, min((today - s.shipment_date).days for s in shipments)) if shipments else None
    )

    breakdown = score_buyer(
        ScoringInput(
            product_hs_code=product.hs_code,
            buyer_hs_codes=buyer_hs,
            shipment_count_12m=len(recent),
            total_value_usd_12m=total_value,
            days_since_last_shipment=last_days,
            buyer_country_iso2=buyer.country_iso2,
            employee_count=buyer.employee_count,
            source=SourceType(buyer.source.value),
        )
    )

    evidence = _evidence(recent, buyer.source.value, product.hs_code)
    match = db.scalar(
        select(ProductBuyerMatch).where(
            ProductBuyerMatch.product_id == product.id,
            ProductBuyerMatch.buyer_id == buyer.id,
        )
    )
    if match is None:
        match = ProductBuyerMatch(product_id=product.id, buyer_id=buyer.id)
        db.add(match)
    match.market_iso2 = market_iso2
    match.relevance_score = breakdown.total
    match.score_breakdown = breakdown.as_dict()
    match.evidence = evidence
    db.flush()


def _evidence(recent_shipments: list, source: str, hs_code: str) -> dict:
    if recent_shipments:
        return {
            "type": "customs",
            "summary": (
                f"Imported {len(recent_shipments)} shipments of HS {hs_code} in the last 12 months"
            ),
            "shipment_count": len(recent_shipments),
        }
    return {
        "type": source,
        "summary": "Discovered via business directory; no customs history on file",
        "shipment_count": 0,
    }


def _domain_from_url(url: str) -> str | None:
    cleaned = url.replace("https://", "").replace("http://", "").split("/")[0]
    return cleaned or None


def buyers_for_product(
    db: Session, product_id: uuid.UUID, market_iso2: str | None = None
) -> list[tuple[ProductBuyerMatch, Buyer]]:
    """Ranked (match, buyer) pairs for a product, highest score first."""
    query = (
        select(ProductBuyerMatch, Buyer)
        .join(Buyer, Buyer.id == ProductBuyerMatch.buyer_id)
        .where(ProductBuyerMatch.product_id == product_id)
        .order_by(ProductBuyerMatch.relevance_score.desc())
    )
    if market_iso2:
        query = query.where(ProductBuyerMatch.market_iso2 == market_iso2)
    return list(db.execute(query).all())

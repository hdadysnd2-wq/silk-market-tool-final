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


class HsNotConfirmedError(ValueError):
    """Discovery attempted on an HS code the human has not confirmed (I2).

    Subclasses ``ValueError`` so existing broad ``except ValueError`` handlers
    keep working, while callers that care can distinguish the confirmation gate
    from an unclassified product.
    """


_SEARCH_TERMS = {
    "39": "plastics packaging distributor importer",
    "08": "dates dried fruit importer distributor",
    "17": "confectionery sweets importer distributor",
    "19": "bakery biscuits importer distributor",
    "20": "food preserves importer distributor",
    "04": "dairy foods importer distributor",
}


def discover_buyers(
    db: Session,
    product: Product,
    market_iso2: str,
    analysis_id: uuid.UUID | None = None,
) -> dict:
    """Run the full pipeline; return a small summary for logging/telemetry.

    ``analysis_id`` is the analysis this fetch serves (decision #6 / I8 — leads
    are fetched in service of a specific analysis, never bulk pre-fetched); the
    API route always supplies it, and every match row is stamped with it.
    """
    if not product.hs_code:
        raise ValueError("Product must be classified before discovery")
    # I2 (defense-in-depth). Discovery fetches buyer PII and must run only on a
    # *human-confirmed* HS code. The API route (``api/buyers.discover``) already
    # checks this, but the classifier pre-fills ``hs_code`` with its top candidate
    # before the user confirms — so ``hs_code`` alone is not proof of confirmation,
    # and a direct service/worker invocation would otherwise bypass the gate.
    # Re-checking here makes the gate hold on every code path, mirroring the
    # three-layer discipline the send path uses for I3.
    if not product.hs_confirmed_by_user:
        raise HsNotConfirmedError("HS code must be confirmed before discovering buyers")

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

    #: Buyers this run actually touched (new or deduped-onto) — step 3 is
    #: scoped to them, insertion-ordered.
    touched: dict[uuid.UUID, Buyer] = {}

    discovered = 0
    for name, records in grouped.items():
        buyer = _upsert_buyer(
            db,
            existing_index,
            name,
            market_iso2,
            BuyerSource.customs,
            confidence=records[0].confidence,
            provider_name=records[0].provider_name,
        )
        _store_shipments(db, buyer, records)
        touched[buyer.id] = buyer
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
            provider_name=rec.provider_name,
        )
        touched[buyer.id] = buyer
        buyer.legal_review_required = True
        if rec.data.website and not buyer.website:
            buyer.website = rec.data.website
            buyer.domain = buyer.domain or _domain_from_url(rec.data.website)
        if rec.data.phone and not buyer.phone:
            buyer.phone = rec.data.phone
        if rec.data.address and not buyer.address:
            buyer.address = rec.data.address

    # --- 2b. Engine importer-intel (Volza / Explee) — additional, fail-closed.
    # Registered only with a paid key; the wrapped engine agents additionally
    # refuse to run outside the deepen scope (engine invariant A4), so this
    # yields nothing on the free path — the customs + maps sources above stay
    # primary. Surfaced names carry their own BuyerSource.importer_intel
    # provenance and the platform's usual legal-review flag for outreach.
    from app.providers.registry import get_importer_intel_providers

    for provider in get_importer_intel_providers():
        for rec in provider.named_importers(
            hs_code, market_iso2, product_name=product.name_en or product.name_ar
        ):
            buyer = _upsert_buyer(
                db,
                existing_index,
                rec.data.name,
                market_iso2,
                BuyerSource.importer_intel,
                confidence=rec.confidence,
                provider_name=rec.provider_name,
            )
            touched[buyer.id] = buyer
            buyer.legal_review_required = True

    db.flush()

    # --- 3. Enrichment + contacts + scoring per buyer ------------------------
    # Scoped to the buyers THIS run touched. Iterating every buyer in the
    # country (as before) made one discovery click O(country-table): ~3 queries
    # + scoring per row for thousands of rows another factory discovered — and
    # minted ProductBuyerMatch rows for buyers unrelated to this fetch (I8).
    scored = 0
    for buyer in touched.values():
        _enrich(db, buyer, settings_providers["enrichment"])
        _find_contacts(db, buyer, settings_providers["waterfall"])
        _score(db, product, buyer, market_iso2, analysis_id=analysis_id)
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
    provider_name: str | None = None,
) -> Buyer:
    norm = normalization.normalize_name(name)
    # Exact hit first — only a miss pays for the O(country-buyers) fuzzy scan
    # (which previously also rebuilt a throwaway {k: k} dict per candidate).
    hit = index.get(norm)
    if hit is not None:
        # Backfill provenance if the existing row never captured it.
        if provider_name and not hit.provider_name:
            hit.provider_name = provider_name
        return hit
    dup_key = normalization.find_duplicate(name, index)
    if dup_key and dup_key in index:
        return index[dup_key]

    buyer = Buyer(
        name=name,
        normalized_name=norm,
        country_iso2=market_iso2,
        source=source,
        source_confidence=confidence,
        # The actual discovery adapter (e.g. "customs_sample", "outscraper",
        # "volza") — carried so the executive report can honestly mark a
        # demonstration-sourced buyer rather than presenting it as observed
        # customs data (audit C6, I1).
        provider_name=provider_name,
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


def _score(
    db: Session,
    product: Product,
    buyer: Buyer,
    market_iso2: str,
    analysis_id: uuid.UUID | None = None,
) -> None:
    shipments = db.scalars(select(Shipment).where(Shipment.buyer_id == buyer.id)).all()

    today = utcnow().date()
    # A provider gap can leave shipment_date None; exclude those from the date
    # math so one dateless row can't crash the whole discovery task (I1 spirit).
    dated = [s for s in shipments if s.shipment_date is not None]
    recent = [s for s in dated if 0 <= (today - s.shipment_date).days <= 365]
    total_value = sum(float(s.value_usd or 0) for s in recent)
    buyer_hs = sorted({s.hs_code for s in shipments}) or [product.hs_code]
    last_days = max(0, min((today - s.shipment_date).days for s in dated)) if dated else None

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
    # I8 — record the lawful basis for direct marketing to this lead, derived from
    # the evidence that established it (PDPL Art. 25 prior-interaction / GDPR).
    match.lawful_basis, match.basis_note = _lawful_basis(shipments, evidence)
    # Decision #6 / I8 — stamp the analysis this fetch served (None only for
    # direct service invocations outside the product flow, e.g. legacy rows).
    if analysis_id is not None:
        match.analysis_id = analysis_id
    db.flush()


def _lawful_basis(shipments: list, evidence: dict) -> tuple[str, str]:
    """Lawful basis + note for contacting this lead (I8 / PDPL Art. 25 / GDPR).

    Import history on file is a prior commercial interaction with the product
    category — the basis for B2B direct marketing under Saudi PDPL Art. 25 and a
    GDPR legitimate-interest basis. A directory-only lead has no such history and
    is flagged for review before any outreach. Never asserts consent that was not
    established — a weaker basis is labelled as such, not inflated.
    """
    if shipments:
        note = (
            f"{evidence.get('summary', 'Import history on file')} — prior commercial "
            "activity supports B2B direct marketing (PDPL Art. 25 prior-interaction "
            "basis; GDPR legitimate interest)."
        )
        return "prior_import_activity", note
    return (
        "directory_listing",
        "Public business-directory listing; no import history on file — review the "
        "lawful basis before direct marketing.",
    )


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
    db: Session,
    product_id: uuid.UUID,
    market_iso2: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[tuple[ProductBuyerMatch, Buyer]]:
    """Ranked (match, buyer) pairs for a product, highest score first.

    ``limit``/``offset`` are pushed into SQL (audit H2) so a polled buyers view
    fetches only the requested page from Postgres rather than materializing every
    match row (~220 per market) and slicing in Python.
    """
    query = (
        select(ProductBuyerMatch, Buyer)
        .join(Buyer, Buyer.id == ProductBuyerMatch.buyer_id)
        .where(ProductBuyerMatch.product_id == product_id)
        .order_by(ProductBuyerMatch.relevance_score.desc())
    )
    if market_iso2:
        query = query.where(ProductBuyerMatch.market_iso2 == market_iso2)
    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return list(db.execute(query).all())

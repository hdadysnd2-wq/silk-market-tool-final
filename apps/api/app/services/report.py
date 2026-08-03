"""Assemble a product's export-intelligence report.

The report gathers, for one product, everything the pipeline has produced so far:
the confirmed HS classification, the competitor snapshot per analyzed market, and
the ranked buyers with their contacts. It is intentionally read-only — it reads
cached snapshots rather than re-fetching them, so viewing (or downloading) a
report never triggers an external API call or a database write.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Analysis,
    Buyer,
    Contact,
    CountryRanking,
    Factory,
    HSCode,
    Market,
    MarketSnapshot,
    Product,
    utcnow,
)
from app.providers.countries import iso3_to_iso2
from app.schemas.report import (
    ProductReportOut,
    ReportBuyer,
    ReportContact,
    ReportExporter,
    ReportFactory,
    ReportFunnel,
    ReportFunnelMarket,
    ReportMarket,
    ReportProduct,
    ReportSnapshot,
    ReportSummary,
    ReportYear,
)
from app.services.buyer_discovery import buyers_for_product

#: How many top-ranked buyers to surface per market in the report.
TOP_BUYERS_PER_MARKET = 5

#: How many world-funnel markets to surface in the report's shortlist.
TOP_FUNNEL_MARKETS = 5

_VERIFIED_STATUSES = {"valid"}


def build_product_report(db: Session, product: Product, locale: str = "en") -> ProductReportOut:
    factory = db.get(Factory, product.factory_id)
    if factory is None:  # pragma: no cover - a product always has a factory
        raise ValueError("Product is not linked to a factory")

    hs = db.get(HSCode, product.hs_code) if product.hs_code else None

    matches = buyers_for_product(db, product.id)
    by_market: dict[str, list[tuple]] = defaultdict(list)
    for match, buyer in matches:
        by_market[match.market_iso2].append((match, buyer))

    markets = [
        _market_section(db, product, iso2, pairs) for iso2, pairs in sorted(by_market.items())
    ]

    # Largest current-year import value first, so the most significant market leads.
    def _market_value(m: ReportMarket) -> float:
        return (m.snapshot.total_import_usd if m.snapshot else 0) or 0

    markets.sort(key=_market_value, reverse=True)

    return ProductReportOut(
        generated_at=utcnow(),
        locale=locale,
        factory=_factory_section(factory),
        product=_product_section(product, hs),
        summary=_summary(markets),
        funnel=_funnel_section(db, product),
        markets=markets,
    )


def _funnel_section(db: Session, product: Product) -> ReportFunnel | None:
    """The latest analysis's "world screened → top N", or None if none has run.

    Read-only: reads the persisted shortlist (transit-flagged, year-stamped),
    never re-screens. A market with no reported imports keeps ``import_usd=None``
    — a declared gap (I1), never a fabricated figure.
    """
    analysis = db.scalar(
        select(Analysis)
        .where(Analysis.product_id == product.id)
        .order_by(Analysis.created_at.desc())
    )
    if analysis is None:
        return None

    rankings = list(
        db.scalars(
            select(CountryRanking)
            .where(CountryRanking.analysis_id == analysis.id)
            .order_by(CountryRanking.rank)
        )
    )
    top = [
        ReportFunnelMarket(
            rank=r.rank,
            importer_iso3=r.importer_iso3,
            market_iso2=iso3_to_iso2(r.importer_iso3),
            year=r.year,
            import_usd=float(r.import_usd) if r.import_usd is not None else None,
            is_transit_hub=r.is_transit_hub,
            is_mirror=r.is_mirror,
            tags=r.tags,
        )
        for r in rankings[:TOP_FUNNEL_MARKETS]
    ]
    return ReportFunnel(
        hs_code=product.hs_code,
        shortlisted_count=len(rankings),
        top_markets=top,
    )


def _factory_section(factory: Factory) -> ReportFactory:
    return ReportFactory(
        name_en=factory.name_en,
        name_ar=factory.name_ar,
        sector=factory.sector,
        city=factory.city,
        website=factory.website,
        contact_person=factory.contact_person,
        contact_email=factory.contact_email,
        contact_phone=factory.contact_phone,
    )


def _product_section(product: Product, hs: HSCode | None) -> ReportProduct:
    return ReportProduct(
        id=product.id,
        name_en=product.name_en,
        name_ar=product.name_ar,
        description_en=product.description_en,
        description_ar=product.description_ar,
        image_url=product.image_url,
        price_min=float(product.price_min) if product.price_min is not None else None,
        price_max=float(product.price_max) if product.price_max is not None else None,
        currency=product.currency,
        hs_code=product.hs_code,
        hs_description_en=hs.description_en if hs else None,
        hs_description_ar=hs.description_ar if hs else None,
        hs_confirmed_by_user=product.hs_confirmed_by_user,
        classification_status=product.classification_status,
        hs_confidence=_hs_confidence(product),
    )


def _hs_confidence(product: Product) -> float | None:
    """Confidence the classifier assigned to the product's chosen HS code."""
    if not product.hs_code or not product.hs_candidates:
        return None
    for candidate in product.hs_candidates:
        if candidate.get("code") == product.hs_code:
            value = candidate.get("confidence")
            return float(value) if value is not None else None
    return None


def _market_section(db: Session, product: Product, iso2: str, pairs: list[tuple]) -> ReportMarket:
    market = db.get(Market, iso2)
    snapshot = None
    if product.hs_code:
        snapshot = db.scalar(
            select(MarketSnapshot).where(
                MarketSnapshot.hs_code == product.hs_code,
                MarketSnapshot.market_iso2 == iso2,
            )
        )

    top_buyers: list[ReportBuyer] = []
    contact_count = 0
    for match, buyer in pairs:
        contacts = db.scalars(select(Contact).where(Contact.buyer_id == buyer.id)).all()
        contact_count += len(contacts)
        if len(top_buyers) < TOP_BUYERS_PER_MARKET:
            top_buyers.append(_buyer_section(match, buyer, contacts))

    return ReportMarket(
        iso2=iso2,
        name_en=market.name_en if market else iso2,
        name_ar=market.name_ar if market else iso2,
        is_gcc=market.is_gcc if market else False,
        is_eu=market.is_eu if market else False,
        is_us=market.is_us if market else False,
        buyer_count=len(pairs),
        contact_count=contact_count,
        snapshot=_snapshot_section(snapshot) if snapshot else None,
        top_buyers=top_buyers,
    )


def _buyer_section(match, buyer: Buyer, contacts: list[Contact]) -> ReportBuyer:
    evidence = match.evidence or {}
    return ReportBuyer(
        name=buyer.name,
        city=buyer.city,
        website=buyer.website,
        industry=buyer.industry,
        employee_count=buyer.employee_count,
        source=buyer.source.value if hasattr(buyer.source, "value") else str(buyer.source),
        relevance_score=match.relevance_score,
        evidence_summary=evidence.get("summary"),
        legal_review_required=buyer.legal_review_required,
        contacts=[
            ReportContact(
                full_name=c.full_name,
                title=c.title,
                email=c.email,
                verification_status=(
                    c.verification_status.value
                    if hasattr(c.verification_status, "value")
                    else str(c.verification_status)
                ),
            )
            for c in contacts
        ],
    )


def _snapshot_section(snapshot: MarketSnapshot) -> ReportSnapshot:
    return ReportSnapshot(
        total_import_usd=(
            float(snapshot.total_import_usd) if snapshot.total_import_usd is not None else None
        ),
        trend_pct=float(snapshot.trend_pct) if snapshot.trend_pct is not None else None,
        top_exporters=[
            ReportExporter(
                exporter_iso2=e.get("exporter_iso2"),
                exporter_name=e.get("exporter_name"),
                value_usd=e.get("value_usd"),
                share_pct=e.get("share_pct"),
            )
            for e in (snapshot.top_exporters or [])
        ],
        yearly_values=[
            ReportYear(year=y["year"], value_usd=y.get("value_usd"))
            for y in (snapshot.yearly_values or [])
        ],
        source=snapshot.source,
    )


def _summary(markets: list[ReportMarket]) -> ReportSummary:
    total_buyers = sum(m.buyer_count for m in markets)
    total_contacts = sum(m.contact_count for m in markets)
    verified = sum(
        1
        for m in markets
        for b in m.top_buyers
        for c in b.contacts
        if c.verification_status in _VERIFIED_STATUSES
    )

    valued = [
        (m.iso2, m.snapshot.total_import_usd)
        for m in markets
        if m.snapshot and m.snapshot.total_import_usd is not None
    ]
    total_import = sum(v for _, v in valued) if valued else None
    top_market = max(valued, key=lambda pair: pair[1])[0] if valued else None

    return ReportSummary(
        markets_analyzed=len(markets),
        total_buyers=total_buyers,
        total_contacts=total_contacts,
        verified_contacts=verified,
        total_import_usd=total_import,
        top_market_iso2=top_market,
    )

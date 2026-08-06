"""AI email drafting.

Builds one personalized draft per buyer contact using the factory profile, the
product, and the buyer's import evidence, in the buyer's language. After the LLM
returns, a validator guarantees the two legally required elements — a working
unsubscribe link and the sender's real identity/address — are present, appending
them if the model left them out. Drafts are always created in ``draft`` status;
they never send on their own.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging import get_logger
from app.models import (
    Buyer,
    Campaign,
    Contact,
    Email,
    EmailStatus,
    Factory,
    Product,
    ProductBuyerMatch,
)
from app.providers.base import LLMMessage, LLMProvider
from app.providers.countries import LANGUAGE_NAMES, country_name
from app.providers.llm.prompts import (
    EMAIL_SYSTEM_PROMPT,
    OUTREACH_EMAIL_SCHEMA,
    email_user_prompt,
)

log = get_logger(__name__)


def unsubscribe_url(token: str) -> str:
    # Must target the API origin: the /u/{token} handlers are mounted on the
    # FastAPI root, and the web app neither serves nor proxies /u — a link built
    # from app_base_url 404s for every recipient (and poisons the RFC 8058
    # List-Unsubscribe headers that reuse this URL).
    base = get_settings().api_base_url.rstrip("/")
    return f"{base}/u/{token}"


def _postal_address(factory: Factory) -> str:
    """The physical postal address line required by CAN-SPAM / PDPL."""
    if factory.postal_address:
        return factory.postal_address
    return f"{factory.city or ''}, Saudi Arabia".strip(", ")


def build_signature(factory: Factory, language: str) -> str:
    """Sender-identity block appended to every email (CAN-SPAM / PDPL)."""
    lines = [
        factory.contact_person or factory.name_en,
        factory.name_en,
        _postal_address(factory),
    ]
    if factory.contact_email:
        lines.append(factory.contact_email)
    if factory.contact_phone:
        lines.append(factory.contact_phone)
    return "\n".join(line for line in lines if line)


def _unsubscribe_line(url: str, language: str) -> str:
    templates = {
        "en": f"To stop receiving emails from us, unsubscribe here: {url}",
        "es": f"Para dejar de recibir correos nuestros, cancele la suscripción aquí: {url}",
        "pt": f"Para deixar de receber os nossos e-mails, cancele a subscrição aqui: {url}",
        "fr": f"Pour ne plus recevoir nos e-mails, désabonnez-vous ici : {url}",
        "hi": f"हमारे ईमेल प्राप्त करना बंद करने के लिए यहाँ सदस्यता समाप्त करें: {url}",
    }
    return templates.get(language, templates["en"])


def ensure_compliance_footer(body: str, factory: Factory, language: str, unsub_url: str) -> str:
    """Guarantee the sender identity and unsubscribe link are both present."""
    result = body.rstrip()

    signature = build_signature(factory, language)
    # The identity guard must ensure BOTH the sender's name and the physical
    # postal address are present — a body that merely names the company is still
    # non-compliant without the address, so key the check on the address line.
    postal_address = _postal_address(factory).lower()
    lowered = result.lower()
    if factory.name_en.lower() not in lowered or (postal_address and postal_address not in lowered):
        result = f"{result}\n\n{signature}"

    if unsub_url not in result:
        result = f"{result}\n\n{_unsubscribe_line(unsub_url, language)}"

    return result


def draft_email_for_contact(
    db: Session,
    *,
    campaign: Campaign,
    product: Product,
    factory: Factory,
    buyer: Buyer,
    contact: Contact,
    match: ProductBuyerMatch | None,
    llm: LLMProvider,
) -> Email:
    language = contact.language or "en"
    evidence = (
        match.evidence.get("summary")
        if match and match.evidence
        else f"You appear to import into {country_name(buyer.country_iso2)}."
    )

    price_range = None
    if product.price_min and product.price_max:
        price_range = f"{product.currency} {product.price_min:.0f}–{product.price_max:.0f}"

    context = {
        "language_name": LANGUAGE_NAMES.get(language, "English"),
        "factory_name": factory.name_en,
        "factory_sector": factory.sector,
        "factory_description": factory.description_en,
        "product_name": product.name_en,
        "product_description": product.description_en,
        "hs_code": product.hs_code,
        "price_range": price_range,
        "buyer_name": buyer.name,
        "buyer_country": country_name(buyer.country_iso2),
        "buyer_industry": buyer.industry,
        "contact_name": contact.full_name,
        "contact_title": contact.title,
        "import_evidence": evidence,
    }

    response = llm.complete(
        system=EMAIL_SYSTEM_PROMPT,
        messages=[LLMMessage(role="user", content=email_user_prompt(context))],
        json_schema=OUTREACH_EMAIL_SCHEMA,
        max_tokens=800,
    )
    parsed = response.parsed or {}
    subject = parsed.get("subject") or f"{product.name_en} from {factory.name_en}"
    body = parsed.get("body") or ""

    token = secrets.token_urlsafe(24)
    unsub = unsubscribe_url(token)
    body = ensure_compliance_footer(body, factory, language, unsub)
    body_html = render_html_body(body, token, language)

    email = Email(
        campaign_id=campaign.id,
        contact_id=contact.id,
        buyer_id=buyer.id,
        status=EmailStatus.draft,
        subject=subject[:512],
        body_text=body,
        body_html=body_html,
        language=language,
        unsubscribe_token=token,
        provider_name=response.provider_name,
    )
    db.add(email)
    db.flush()
    return email


def draft_campaign(db: Session, campaign: Campaign, llm: LLMProvider) -> int:
    """Draft one email per verified contact of every buyer matched to the product.

    Returns the number of drafts created. Idempotent: contacts already drafted
    for this campaign are skipped.
    """
    product = db.get(Product, campaign.product_id)
    factory = db.get(Factory, campaign.factory_id)

    already = {
        row.contact_id
        for row in db.execute(
            select(Email.contact_id).where(Email.campaign_id == campaign.id)
        ).all()
    }

    matches = db.execute(
        select(ProductBuyerMatch, Buyer)
        .join(Buyer, Buyer.id == ProductBuyerMatch.buyer_id)
        .where(
            ProductBuyerMatch.product_id == campaign.product_id,
            ProductBuyerMatch.market_iso2 == campaign.market_iso2,
        )
        .order_by(ProductBuyerMatch.relevance_score.desc())
    ).all()

    created = 0
    for match, buyer in matches:
        contacts = db.scalars(select(Contact).where(Contact.buyer_id == buyer.id)).all()
        for contact in contacts:
            if contact.id in already:
                continue
            draft_email_for_contact(
                db,
                campaign=campaign,
                product=product,
                factory=factory,
                buyer=buyer,
                contact=contact,
                match=match,
                llm=llm,
            )
            created += 1

    campaign.total_emails = _count_emails(db, campaign)
    db.flush()
    log.info("campaign_drafted", campaign_id=str(campaign.id), created=created)
    return created


def _count_emails(db: Session, campaign: Campaign) -> int:
    from sqlalchemy import func

    return db.scalar(select(func.count(Email.id)).where(Email.campaign_id == campaign.id)) or 0


def render_html_body(body: str, token: str, language: str) -> str:
    """Render the HTML part of an email body. Public entry point used by both
    the initial draft and any later edit, so an edited body_text always gets a
    matching, regenerated body_html."""
    return _to_html(body, unsubscribe_url(token), language)


def _to_html(body: str, unsub_url: str, language: str) -> str:
    # Only genuinely right-to-left scripts get dir="rtl". Hindi/Devanagari is
    # left-to-right, despite sharing our non-Latin outreach path.
    direction = "rtl" if language in ("ar", "fa", "ur", "he") else "ltr"
    escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    paragraphs = "".join(
        f"<p>{block.strip().replace(chr(10), '<br>')}</p>"
        for block in escaped.split("\n\n")
        if block.strip()
    )
    return f'<div dir="{direction}">{paragraphs}</div>'

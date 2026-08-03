"""End-to-end golden-path demo, driven entirely through the service layer.

Runs the full journey for one seeded factory and prints each step so the whole
flow is reviewable from a terminal without the frontend:

    signup data (seeded) → classify → discover buyers → competitor snapshot →
    create campaign → draft emails → approve one → queue (guarded) → send (mock)
    → synthetic engagement → dashboard stats.

    python -m app.seeds.demo_golden_path
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db import session_scope
from app.models import (
    Buyer,
    Campaign,
    Contact,
    Email,
    EmailStatus,
    Factory,
    Product,
    ProductBuyerMatch,
    User,
    UserRole,
)
from app.providers.registry import get_llm_provider, get_sending_provider
from app.services import approval
from app.services.buyer_discovery import discover_buyers
from app.services.competitor_snapshot import build_snapshot
from app.services.email_drafting import draft_campaign
from app.services.sending import record_engagement, send_email

MARKET = "IN"


def _hr(title: str) -> None:
    print(f"\n{'─' * 68}\n{title}\n{'─' * 68}")


def run() -> None:
    with session_scope() as db:
        factory = db.scalar(select(Factory).where(Factory.name_en == "Jeddah Poly Industries"))
        product = db.scalar(select(Product).where(Product.factory_id == factory.id))
        admin = db.scalar(select(User).where(User.role == UserRole.admin))

        _hr("1. FACTORY & PRODUCT (seeded)")
        print(f"Factory : {factory.name_en} / {factory.name_ar} — {factory.city}")
        print(f"Product : {product.name_en} / {product.name_ar}")
        print(f"HS code : {product.hs_code} (confirmed={product.hs_confirmed_by_user})")
        print("HS candidates from classifier:")
        for cand in product.hs_candidates or []:
            print(f"  - {cand['code']}  conf={cand['confidence']}  {cand.get('rationale', '')}")

        _hr(f"2. BUYER DISCOVERY → market {MARKET}")
        summary = discover_buyers(db, product, MARKET)
        print(f"Discovered {summary['discovered']} companies, scored {summary['scored']}.")

        top = db.execute(
            select(ProductBuyerMatch, Buyer)
            .join(Buyer, Buyer.id == ProductBuyerMatch.buyer_id)
            .where(
                ProductBuyerMatch.product_id == product.id,
                ProductBuyerMatch.market_iso2 == MARKET,
            )
            .order_by(ProductBuyerMatch.relevance_score.desc())
            .limit(5)
        ).all()
        print("\nTop 5 buyers:")
        for match, buyer in top:
            ev = (match.evidence or {}).get("summary", "")
            print(f"  [{match.relevance_score:3d}] {buyer.name} ({buyer.country_iso2}) — {ev}")
            for factor, detail in (match.score_breakdown or {}).get("factors", {}).items():
                print(
                    f"          {factor:14s} {detail['points']:>4}/{detail['max']:<3} {detail['detail']}"
                )
            break  # full breakdown for the top buyer only

        _hr(f"3. COMPETITOR SNAPSHOT (HS {product.hs_code} → {MARKET})")
        snap = build_snapshot(db, product.hs_code, MARKET)
        print(f"Total imports: ${snap.total_import_usd:,.0f}  trend: {snap.trend_pct}%")
        for exp in (snap.top_exporters or [])[:5]:
            print(
                f"  {exp['exporter_name']:20s} {exp['share_pct']:5.1f}%  ${exp['value_usd']:,.0f}"
            )

        _hr("4. CAMPAIGN + AI EMAIL DRAFTING")
        campaign = Campaign(
            factory_id=factory.id,
            product_id=product.id,
            market_iso2=MARKET,
            name=f"{product.name_en} → India",
            created_by=admin.id,
        )
        db.add(campaign)
        db.flush()
        created = draft_campaign(db, campaign, get_llm_provider())
        print(f"Created {created} draft emails (status=draft, nothing sent).")

        sample = db.scalar(select(Email).where(Email.campaign_id == campaign.id).limit(1))
        contact = db.get(Contact, sample.contact_id)
        print(f"\nSample draft → {contact.email} (lang={sample.language}):")
        print(f"Subject: {sample.subject}")
        print(sample.body_text)

        _hr("5. APPROVAL GATE")
        print(f"Before approval: status={sample.status.value}, approved={sample.is_approved}")
        try:
            approval.queue(db, sample, admin)
        except approval.TransitionError as exc:
            print(f"  Queue refused (as required): {exc.detail}")

        approval.approve(db, sample, admin)
        print(f"After approve : status={sample.status.value}, approver={sample.approved_by}")
        approval.queue(db, sample, admin)
        print(f"After queue   : status={sample.status.value}")

        _hr("6. GUARDED SEND (mock provider)")
        sent = send_email(db, sample.id, get_sending_provider())
        print(f"Send result   : status={sent.status.value}, msg_id={sent.provider_message_id}")

        # Simulate engagement the mock would normally POST via webhook.
        record_engagement(db, sent.provider_message_id, "opened")
        record_engagement(db, sent.provider_message_id, "replied")
        db.refresh(sent)
        print(f"After events  : status={sent.status.value}")

        _hr("7. DASHBOARD")
        db.refresh(campaign)
        pending = db.scalar(
            select(func.count(Email.id)).where(
                Email.campaign_id == campaign.id, Email.status == EmailStatus.draft
            )
        )
        print(f"Campaign '{campaign.name}':")
        print(
            f"  sent={campaign.sent_count}  opened={campaign.opened_count} "
            f"replied={campaign.replied_count}  bounced={campaign.bounced_count}"
        )
        print(f"  pending approvals still in queue: {pending}")
        print("\n✓ Golden path complete — one email approved and sent, the rest awaiting review.")


if __name__ == "__main__":
    run()

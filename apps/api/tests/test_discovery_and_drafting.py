"""Buyer discovery pipeline, competitor snapshot, and email drafting."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Buyer, Email
from app.providers.registry import get_llm_provider
from app.services.buyer_discovery import buyers_for_product, discover_buyers
from app.services.competitor_snapshot import build_snapshot
from app.services.email_drafting import draft_campaign
from tests.conftest import make_campaign


def test_discovery_produces_scored_buyers(db, factory, product, market):
    summary = discover_buyers(db, product, "IN")
    db.commit()
    assert summary["discovered"] > 0

    matches = buyers_for_product(db, product.id, "IN")
    assert matches
    # Ranked descending.
    scores = [m.relevance_score for m, _ in matches]
    assert scores == sorted(scores, reverse=True)
    # Breakdown is present and explainable.
    assert matches[0][0].score_breakdown["factors"]["hs_match"]["points"] >= 0


def test_discovery_is_idempotent(db, factory, product, market):
    discover_buyers(db, product, "IN")
    db.commit()
    first = db.scalar(select(func.count(Buyer.id)))

    discover_buyers(db, product, "IN")
    db.commit()
    second = db.scalar(select(func.count(Buyer.id)))
    assert first == second


def test_competitor_snapshot_has_exporters(db, factory, product, market):
    snap = build_snapshot(db, "392010", "IN")
    db.commit()
    assert snap.top_exporters
    assert snap.total_import_usd and snap.total_import_usd > 0


def test_drafts_include_unsubscribe_and_identity(db, factory, product, market):
    discover_buyers(db, product, "IN")
    campaign = make_campaign(db, factory, product)
    created = draft_campaign(db, campaign, get_llm_provider())
    db.commit()
    assert created > 0

    emails = db.scalars(select(Email).where(Email.campaign_id == campaign.id)).all()
    for email in emails:
        # Sender identity present.
        assert factory.name_en.lower() in email.body_text.lower()
        # Working unsubscribe link present.
        assert email.unsubscribe_token in email.body_text
        # Every draft starts as a draft — nothing is auto-approved.
        assert email.status.value == "draft"
        assert email.approved_at is None


def test_draft_language_matches_market(db, factory, product, market):
    discover_buyers(db, product, "IN")
    campaign = make_campaign(db, factory, product)
    draft_campaign(db, campaign, get_llm_provider())
    db.commit()

    # India → Hindi contacts.
    emails = db.scalars(select(Email).where(Email.campaign_id == campaign.id)).all()
    assert emails
    assert all(e.language == "hi" for e in emails)

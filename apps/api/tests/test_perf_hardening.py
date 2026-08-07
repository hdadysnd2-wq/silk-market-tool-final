"""Regression locks for the performance time bombs (Wave 2 item 8).

* The hourly follow-up sweep is one bounded anti-join, not a full-table scan
  with a per-row probe.
* Campaign drafting commits per draft, so a crash never re-pays completed LLM
  calls.
* Buyer discovery scores only the buyers the run touched, not every buyer any
  factory ever discovered in the country.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from app.models import Buyer, BuyerSource, Email, EmailStatus, ProductBuyerMatch, utcnow
from app.services.buyer_discovery import discover_buyers
from app.services.email_drafting import draft_campaign
from app.workers import tasks
from tests.conftest import make_buyer_with_contact, make_campaign, make_draft_email


def _sent_email(db, campaign, buyer, contact, *, days_ago: int) -> Email:
    email = make_draft_email(db, campaign, buyer, contact)
    email.status = EmailStatus.sent
    email.approved_at = utcnow() - timedelta(days=days_ago, hours=1)
    email.sent_at = utcnow() - timedelta(days=days_ago)
    db.commit()
    return email


def test_followup_sweep_antijoin_and_idempotent(db, factory, product):
    campaign = make_campaign(db, factory, product)
    originals = []
    for i in range(3):
        buyer, contact = make_buyer_with_contact(
            db, email=f"b{i}@x.example.in", name=f"Anti Join Buyer {i}"
        )
        originals.append(_sent_email(db, campaign, buyer, contact, days_ago=5))
    # One already has a follow-up: the anti-join must exclude it.
    db.add(
        Email(
            campaign_id=campaign.id,
            contact_id=originals[0].contact_id,
            buyer_id=originals[0].buyer_id,
            status=EmailStatus.draft,
            subject="Re: x",
            body_text="x",
            language="en",
            is_followup=True,
            followup_number=1,
            parent_email_id=originals[0].id,
            unsubscribe_token=secrets.token_urlsafe(24),
        )
    )
    db.commit()

    assert tasks.process_followups.apply().result == {"followup_drafts_created": 2}
    # Second run: everything already has followup 1 — nothing new.
    assert tasks.process_followups.apply().result == {"followup_drafts_created": 0}


def test_followup_sweep_is_bounded(db, factory, product, monkeypatch):
    monkeypatch.setattr(tasks, "FOLLOWUP_BATCH_LIMIT", 2)
    campaign = make_campaign(db, factory, product)
    for i in range(3):
        buyer, contact = make_buyer_with_contact(
            db, email=f"cap{i}@x.example.in", name=f"Cap Buyer {i}"
        )
        _sent_email(db, campaign, buyer, contact, days_ago=5)

    assert tasks.process_followups.apply().result == {"followup_drafts_created": 2}
    # The beat drains the remainder on the next run.
    assert tasks.process_followups.apply().result == {"followup_drafts_created": 1}


def test_draft_campaign_checkpoints_survive_a_crash(db, factory, product, market):
    discover_buyers(db, product, "IN")
    db.commit()
    campaign = make_campaign(db, factory, product)

    class _ExplodingLLM:
        """Succeeds twice, then dies — simulating a crash mid-run."""

        provider_name = "mock"

        def __init__(self):
            self.calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("LLM crashed")
            from app.providers.registry import get_llm_provider

            return get_llm_provider().complete(**kwargs)

    boom = _ExplodingLLM()
    try:
        draft_campaign(db, campaign, boom)
    except RuntimeError:
        db.rollback()

    # The two completed drafts are COMMITTED — visible from a fresh session.
    from app.db import SessionLocal

    with SessionLocal() as fresh:
        persisted = fresh.query(Email).filter(Email.campaign_id == campaign.id).count()
    assert persisted == 2

    # The retry drafts only the remainder: no completed LLM call is re-paid.
    class _CountingLLM:
        provider_name = "mock"

        def __init__(self):
            self.calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            from app.providers.registry import get_llm_provider

            return get_llm_provider().complete(**kwargs)

    counting = _CountingLLM()
    created = draft_campaign(db, campaign, counting)
    assert created == counting.calls
    total = db.query(Email).filter(Email.campaign_id == campaign.id).count()
    assert total == 2 + created


def test_discovery_scoped_to_buyers_touched_this_run(db, factory, product, market):
    # A buyer another factory discovered earlier in the same country, with a
    # name no provider candidate dedups onto.
    unrelated = Buyer(
        name="Unrelated Legacy GmbH",
        normalized_name="unrelated legacy",
        country_iso2="IN",
        source=BuyerSource.customs,
        source_confidence=0.9,
        freshness_at=utcnow(),
    )
    db.add(unrelated)
    db.commit()

    summary = discover_buyers(db, product, "IN")

    matches_for_unrelated = (
        db.query(ProductBuyerMatch)
        .filter(
            ProductBuyerMatch.product_id == product.id,
            ProductBuyerMatch.buyer_id == unrelated.id,
        )
        .count()
    )
    # The old code iterated EVERY buyer in the country and minted a match row
    # for this one too; the run must not touch it.
    assert matches_for_unrelated == 0
    assert summary["scored"] > 0
    # The run's own discoveries are still scored.
    scored_matches = (
        db.query(ProductBuyerMatch).filter(ProductBuyerMatch.product_id == product.id).count()
    )
    assert scored_matches == summary["scored"]

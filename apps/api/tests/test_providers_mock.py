"""Mock providers must be deterministic and schema-compatible with the reals."""

from __future__ import annotations

from app.providers.email_finding.mock import MockEmailFinderProvider
from app.providers.enrichment.mock import MockEnrichmentProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.prompts import (
    OUTREACH_EMAIL_SCHEMA,
    email_user_prompt,
)
from app.providers.shipments.comtrade import ComtradeProvider
from app.providers.shipments.mock import MockShipmentsProvider
from app.providers.verification.mock import MockEmailVerifier


def test_mock_shipments_deterministic():
    a = MockShipmentsProvider().importer_shipments("392010", "IN", limit=30)
    b = MockShipmentsProvider().importer_shipments("392010", "IN", limit=30)
    assert [r.data.consignee_name for r in a] == [r.data.consignee_name for r in b]
    assert [r.data.value_usd for r in a] == [r.data.value_usd for r in b]


def test_mock_enrichment_deterministic():
    a = MockEnrichmentProvider().enrich_company("Acme Ltd", "IN")
    b = MockEnrichmentProvider().enrich_company("Acme Ltd", "IN")
    assert (a is None) == (b is None)
    if a is not None:
        assert a.data.industry == b.data.industry
        assert a.data.employee_count == b.data.employee_count


def test_mock_verifier_deterministic():
    v = MockEmailVerifier()
    assert v.verify("john@acme.com").outcome == v.verify("john@acme.com").outcome


def test_mock_verifier_rejects_malformed():
    from app.providers.base import VerificationOutcome

    assert MockEmailVerifier().verify("not-an-email").outcome == VerificationOutcome.invalid


def test_mock_llm_draft_returns_localized_email():
    llm = MockLLMProvider()
    context = {
        "language_name": "Spanish",
        "factory_name": "Test Co",
        "factory_sector": "plastics",
        "factory_description": "desc",
        "product_name": "Film",
        "product_description": "d",
        "hs_code": "392010",
        "price_range": "USD 1000-2000",
        "buyer_name": "Comprador SA",
        "buyer_country": "Spain",
        "buyer_industry": "packaging",
        "contact_name": "Maria Lopez",
        "contact_title": "Buyer",
        "import_evidence": "Usted importa film.",
    }
    resp = llm.complete(
        system="", messages=[_msg(email_user_prompt(context))], json_schema=OUTREACH_EMAIL_SCHEMA
    )
    assert resp.parsed is not None
    assert "Comprador SA" in resp.parsed["body"]
    assert resp.parsed["subject"]


def test_comtrade_offline_reads_fixtures():
    provider = ComtradeProvider(offline=True)
    flows = provider.trade_flows("392010", "IN", years=3)
    exporters = provider.top_exporters("392010", "IN", limit=5)
    assert flows and all(f.data.value_usd > 0 for f in flows)
    assert exporters and abs(sum(e.data.share_pct for e in exporters) - 100) < 60


def test_email_finder_deterministic():
    a = MockEmailFinderProvider().find_contacts("Acme Ltd", "acme.example.in", "IN")
    b = MockEmailFinderProvider().find_contacts("Acme Ltd", "acme.example.in", "IN")
    assert [r.data.email for r in a] == [r.data.email for r in b]


def _msg(content: str):
    from app.providers.base import LLMMessage

    return LLMMessage(role="user", content=content)

"""Lock C3 (audit 2026-08-07): keyless production must not fabricate data.

Mirror of ``test_no_mock_send_in_prod.py`` for the DATA slots. A keyless deploy
outside ``local`` used to persist the mock price provider's invented
competitors/``listings.example`` URLs into ``MarketSnapshot`` and render them in
the client-facing executive docx, and to score Stage 2 on fabricated tariff/PPP
stamped ``COMTRADE``. Both slots now fail closed to declared gaps (I1).
"""

from __future__ import annotations

from app.config import Settings
from app.providers.base import SourceType
from app.providers.registry import get_market_enrichment_provider, get_price_provider


def _settings(**overrides) -> Settings:
    base = {
        "environment": "production",
        "secret_key": "x" * 40,
        "token_encryption_key": "t" * 44,
    }
    base.update(overrides)
    return Settings(**base)


def test_keyless_prod_prices_are_a_declared_gap():
    provider = get_price_provider(_settings())
    assert provider.name == "gated-prices"
    assert provider.observed_prices("392010", "AE") == []


def test_keyless_prod_enrichment_is_a_declared_gap():
    provider = get_market_enrichment_provider(_settings())
    assert provider.name == "gated-market-enrichment"
    assert provider.enrich_market("ARE", "392010") is None


def test_local_still_gets_deterministic_mocks():
    prices = get_price_provider(_settings(environment="local"))
    assert prices.name == "localprice_mock"
    enrich = get_market_enrichment_provider(_settings(environment="local"))
    assert enrich.name == "market_enrichment_mock"


def test_explicit_demo_opt_in_unlocks_mocks_outside_local():
    settings = _settings(allow_mock_data=True)
    assert get_price_provider(settings).name == "localprice_mock"
    assert get_market_enrichment_provider(settings).name == "market_enrichment_mock"


def test_mock_enrichment_never_wears_a_real_source_label():
    """Fabricated demo values must not carry the COMTRADE label (I1)."""
    record = get_market_enrichment_provider(_settings(environment="local")).enrich_market(
        "ARE", "392010"
    )
    assert record is not None
    assert record.source != SourceType.COMTRADE
    assert record.provider_name == "market_enrichment_mock"

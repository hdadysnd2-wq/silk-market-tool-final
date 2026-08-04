"""Env-driven provider selection.

One rule throughout: if the vendor's API key is present, use the real adapter;
otherwise use the deterministic mock. Comtrade is the exception — it is keyless,
so it is always "real" but wraps a fixture cache for offline use.

The registry is the *only* place that knows which concrete adapter is active, so
services and workers depend on the Protocols alone.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.base import (
    EmailFinderProvider,
    EmailVerifier,
    EmbeddingProvider,
    EnrichmentProvider,
    LLMProvider,
    MailboxProvider,
    MapsProvider,
    MarketEnrichmentProvider,
    PriceProvider,
    SendingProvider,
    ShipmentsProvider,
)
from app.providers.email_finding.waterfall import EmailFindingWaterfall
from app.providers.llm.embeddings import HashingEmbeddingProvider


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if settings.anthropic_api_key:
        from app.providers.llm.anthropic import AnthropicLLMProvider

        return AnthropicLLMProvider(settings.anthropic_api_key, settings.anthropic_model)
    from app.providers.llm.mock import MockLLMProvider

    return MockLLMProvider()


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    # The MVP always uses the deterministic hashing embedder; the seam exists so
    # a hosted embedder can be dropped in without touching callers.
    return HashingEmbeddingProvider()


def get_shipments_provider(settings: Settings | None = None) -> ShipmentsProvider:
    """Comtrade for aggregates; the mock supplies transaction-level rows.

    Comtrade has no company-level shipments, so when only aggregate stats are
    configured we still need a transaction source. The mock customs provider
    fills that role and is always available.
    """
    settings = settings or get_settings()
    from app.providers.shipments.mock import MockShipmentsProvider

    return MockShipmentsProvider(seed=settings.mock_seed)


def get_comtrade_provider(settings: Settings | None = None):
    settings = settings or get_settings()
    from app.providers.shipments.comtrade import ComtradeProvider

    return ComtradeProvider(api_key=settings.comtrade_api_key, offline=settings.comtrade_offline)


def get_price_provider(settings: Settings | None = None) -> PriceProvider:
    """The observed-price layer (paid in production, deepen-gated per I5).

    A real vendor key would select the live adapter here; offline the deterministic
    mock stands in so the deepen path runs end to end without keys.
    """
    settings = settings or get_settings()
    from app.providers.pricing.mock import MockPriceProvider

    return MockPriceProvider(seed=settings.mock_seed)


def get_market_enrichment_provider(
    settings: Settings | None = None,
) -> MarketEnrichmentProvider:
    """The Stage-2 market-enrichment layer (applied tariff + PPP).

    Live (``MARKET_ENRICHMENT_LIVE=1``) selects the World Bank / WITS adapter, which
    routes tariff + PPP fetches through the engine's hardened data layer (provenance /
    throttle / circuit-breaker / cache inherited, locked decision #5). Offline (the
    default) the deterministic mock stands in so the funnel's Stage 2 runs end to end
    without keys — keeping CI offline-green.
    """
    settings = settings or get_settings()
    if settings.market_enrichment_live:
        from app.providers.market_enrichment.worldbank_wits import (
            WorldBankWitsEnrichmentProvider,
        )

        return WorldBankWitsEnrichmentProvider()
    from app.providers.market_enrichment.mock import MockMarketEnrichmentProvider

    return MockMarketEnrichmentProvider(seed=settings.mock_seed)


def get_enrichment_provider(settings: Settings | None = None) -> EnrichmentProvider:
    settings = settings or get_settings()
    if settings.coresignal_api_key:
        from app.providers.enrichment.coresignal import CoresignalProvider

        return CoresignalProvider(settings.coresignal_api_key)
    from app.providers.enrichment.mock import MockEnrichmentProvider

    return MockEnrichmentProvider(seed=settings.mock_seed)


def get_maps_provider(settings: Settings | None = None) -> MapsProvider:
    settings = settings or get_settings()
    if settings.outscraper_api_key:
        from app.providers.maps.outscraper import OutscraperMapsProvider

        return OutscraperMapsProvider(settings.outscraper_api_key)
    from app.providers.maps.mock import MockMapsProvider

    return MockMapsProvider(seed=settings.mock_seed)


def get_email_finder(settings: Settings | None = None) -> EmailFinderProvider:
    settings = settings or get_settings()
    if settings.apollo_api_key:
        from app.providers.email_finding.apollo import ApolloEmailFinderProvider

        return ApolloEmailFinderProvider(settings.apollo_api_key)
    from app.providers.email_finding.mock import MockEmailFinderProvider

    return MockEmailFinderProvider(seed=settings.mock_seed)


def get_email_verifier(settings: Settings | None = None) -> EmailVerifier:
    settings = settings or get_settings()
    if settings.zerobounce_api_key:
        from app.providers.verification.zerobounce import ZeroBounceVerifier

        return ZeroBounceVerifier(settings.zerobounce_api_key)
    from app.providers.verification.mock import MockEmailVerifier

    return MockEmailVerifier(seed=settings.mock_seed)


def get_email_waterfall(settings: Settings | None = None) -> EmailFindingWaterfall:
    settings = settings or get_settings()
    return EmailFindingWaterfall(get_email_finder(settings), get_email_verifier(settings))


def get_sending_provider(settings: Settings | None = None) -> SendingProvider:
    settings = settings or get_settings()
    if settings.smartlead_api_key:
        from app.providers.sending.smartlead import SmartleadSendingProvider

        return SmartleadSendingProvider(settings.smartlead_api_key)
    from app.providers.sending.mock import MockSendingProvider

    return MockSendingProvider(
        api_base_url=settings.api_base_url,
        emit_engagement=settings.mock_emit_engagement,
        seed=settings.mock_seed,
        webhook_secret=settings.smartlead_webhook_secret,
    )


def get_mailbox_provider(provider_type: str, settings: Settings | None = None) -> MailboxProvider:
    """Return the mailbox adapter for a connected sender account.

    Selection follows the platform rule: use the real Gmail / Microsoft adapter
    when that provider's OAuth client credentials are configured, otherwise fall
    back to the deterministic mock — which simulates the whole OAuth handshake so
    the connect→verify→send flow works with no external app (demos, CI, e2e). The
    mock keeps the requested ``provider_type`` label so the UI reflects the intent.
    """
    settings = settings or get_settings()

    if (
        provider_type == "gmail"
        and settings.google_oauth_client_id
        and settings.google_oauth_client_secret
    ):
        from app.providers.sending.gmail_oauth import GmailOAuthProvider

        return GmailOAuthProvider(
            settings.google_oauth_client_id, settings.google_oauth_client_secret
        )

    if (
        provider_type == "microsoft"
        and settings.microsoft_oauth_client_id
        and settings.microsoft_oauth_client_secret
    ):
        from app.providers.sending.microsoft_oauth import MicrosoftGraphProvider

        return MicrosoftGraphProvider(
            settings.microsoft_oauth_client_id,
            settings.microsoft_oauth_client_secret,
            settings.microsoft_oauth_tenant,
        )

    from app.providers.sending.mock import MockMailboxProvider

    return MockMailboxProvider(provider_type=provider_type)


@lru_cache
def active_provider_summary() -> dict[str, str]:
    """Human-readable map of which adapter is live per slot (for /health, docs)."""
    settings = get_settings()
    return {
        "llm": get_llm_provider(settings).name,
        "embedding": get_embedding_provider(settings).name,
        "shipments": get_shipments_provider(settings).name,
        "comtrade": get_comtrade_provider(settings).name,
        "enrichment": get_enrichment_provider(settings).name,
        "maps": get_maps_provider(settings).name,
        "email_finder": get_email_finder(settings).name,
        "email_verifier": get_email_verifier(settings).name,
        "sending": get_sending_provider(settings).name,
    }

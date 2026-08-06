"""Application settings.

Every external vendor is optional: a blank key means the provider registry
selects the deterministic mock adapter instead, so the platform runs end to end
with no third-party accounts.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET_DEFAULT = "dev-secret-key-not-for-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Core
    environment: str = "local"
    secret_key: str = _DEV_SECRET_DEFAULT
    database_url: str = "postgresql+psycopg://silk:silk@localhost:5432/silk"
    redis_url: str = "redis://localhost:6379/0"
    api_base_url: str = "http://localhost:8000"
    app_base_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"

    access_token_ttl_minutes: int = 60 * 12
    otp_ttl_minutes: int = 10
    # OTP one-time codes are delivered out-of-band. The plaintext code is only
    # ever returned in the HTTP response when BOTH the environment is local AND
    # this flag is explicitly set (SILK_DEV_EXPOSE_OTP=1) — never in staging/prod.
    silk_dev_expose_otp: bool = False
    # Wrong-OTP attempts allowed before the code is locked (online brute-force cap).
    otp_max_attempts: int = 5

    # PDPL data-minimisation: contacts older than this whose campaign work is
    # done have their personal data anonymised by the daily retention sweep.
    pdpl_retention_days: int = 180

    # Storage
    storage_backend: str = "local"  # "local" | "s3"
    storage_local_dir: str = "./storage"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "silk-products"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "me-south-1"

    # Vendors — blank means "use the mock adapter"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-fable-5"
    comtrade_api_key: str = ""
    comtrade_offline: bool = True
    # Stage-2 market enrichment (applied tariff + PPP). Blank/False keeps the
    # deterministic mock so CI/offline stays green; True selects the LIVE World
    # Bank / WITS adapter, which routes through the engine's hardened data layer.
    market_enrichment_live: bool = False
    # Observed-price layer (paid, deepen-gated). Blank keeps the deterministic
    # MockPriceProvider so CI/offline stays green; a value selects the LIVE
    # LocalPriceProvider, which routes through the engine's paid LocalPriceAgent.
    # This field is only the registry's switch signal — the engine agent reads its
    # own vendor key from the environment; the adapter never passes it.
    serper_api_key: str = ""
    coresignal_api_key: str = ""
    outscraper_api_key: str = ""
    apollo_api_key: str = ""
    zerobounce_api_key: str = ""
    smartlead_api_key: str = ""
    smartlead_webhook_secret: str = ""
    # Fail-closed gate on the Smartlead cold-send slot.
    #
    # Setting SMARTLEAD_API_KEY alone flips the slot live, but the adapter's
    # one-click List-Unsubscribe (RFC 8058) headers are emitted by the Smartlead
    # *campaign sequence template*, from the custom fields the adapter sends —
    # a console step no offline test can prove. Until an operator has configured
    # that template and confirmed it (see docs/PHASE3_ADAPTER_READINESS.md), the
    # registry hands out a gate that refuses every send instead of the live
    # adapter, so an unproven cold-send path can never put mail on the wire
    # without its legally required unsubscribe headers (I4).
    smartlead_sequence_verified: bool = False

    # DKIM selectors probed by the deliverability DNS check (comma-separated).
    # The record lives at "<selector>._domainkey.<domain>"; different providers
    # publish under different selectors (Google → google, Microsoft →
    # selector1/2, etc.), so we try a small set and pass if any resolves.
    dkim_selectors: str = "default,google,selector1,selector2,s1,s2,k1,smartlead,dkim"

    sentry_dsn: str = ""

    # Per-tenant mailbox OAuth (multi-tenant email sending).
    #
    # Each factory connects its own Gmail / Microsoft mailbox; the platform sends
    # on that account's behalf via the Gmail / Microsoft Graph APIs. When a
    # provider's client id/secret is blank the registry falls back to the
    # deterministic mock mailbox adapter — so the whole connect→verify→send flow
    # runs end to end with no Google/Microsoft app configured (demos, CI, e2e).
    #
    # Tokens are encrypted at rest with Fernet. ``token_encryption_key`` should be
    # a url-safe base64 32-byte key (``Fernet.generate_key()``); when blank a key
    # is deterministically derived from ``secret_key`` so dev/test still encrypt.
    token_encryption_key: str = ""

    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    microsoft_oauth_client_id: str = ""
    microsoft_oauth_client_secret: str = ""
    # "common" lets any work/school or personal MS account connect.
    microsoft_oauth_tenant: str = "common"

    # Where providers redirect back after consent. Defaults to this API's own
    # callback under ``api_base_url``; override when the public URL differs.
    oauth_redirect_base_url: str = ""
    # Frontend page the callback bounces the browser to once a mailbox connects.
    oauth_post_connect_path: str = "/onboarding/email"
    oauth_state_ttl_minutes: int = 15

    # New sender accounts start their warm-up here (emails/day), ramping on the
    # daily ``advance_sender_warmup`` beat. Ceiling per account:
    sender_default_daily_limit: int = 50
    # How far back the reply-detection beat looks when polling a mailbox.
    reply_poll_lookback_minutes: int = 120

    # Deliverability guardrails
    max_emails_per_inbox_per_day: int = 50
    warmup_days: int = 14
    bounce_rate_pause_threshold: float = 0.05
    complaint_rate_pause_threshold: float = 0.001

    # Mock behaviour (kept deterministic for demos and tests)
    mock_seed: int = 42
    mock_emit_engagement: bool = True

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Force the psycopg (v3) driver on managed-platform URLs.

        Railway, Heroku, and most managed Postgres providers hand out URLs like
        ``postgres://…`` or ``postgresql://…``. SQLAlchemy maps a bare
        ``postgresql://`` to psycopg2, which is not installed — this project uses
        psycopg 3. Rewrite the scheme so the platform-provided ``DATABASE_URL``
        works unchanged, while leaving an explicit ``postgresql+psycopg://`` (or
        any other driver already specified) untouched.
        """
        if not isinstance(value, str) or "://" not in value:
            return value
        scheme, rest = value.split("://", 1)
        if scheme in ("postgres", "postgresql"):
            return f"postgresql+psycopg://{rest}"
        return value

    @model_validator(mode="after")
    def _reject_default_secret_outside_local(self) -> Settings:
        """Fail closed if SECRET_KEY is still the built-in dev default in a
        non-local environment. The default is public, so signing tokens with it
        lets anyone forge an admin session (and derives a public mailbox
        token-encryption key). Local dev/CI keep the default; staging/prod must
        set a real SECRET_KEY.
        """
        if self.environment.strip().lower() != "local" and (self.secret_key == _DEV_SECRET_DEFAULT):
            raise ValueError(
                "SECRET_KEY is unset (still the built-in dev default) but "
                f"ENVIRONMENT={self.environment!r} is not 'local'. Set a strong, "
                "random SECRET_KEY — it signs session tokens and derives the "
                "mailbox token-encryption key."
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

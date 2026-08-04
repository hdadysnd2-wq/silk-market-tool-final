"""Application settings.

Every external vendor is optional: a blank key means the provider registry
selects the deterministic mock adapter instead, so the platform runs end to end
with no third-party accounts.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Core
    environment: str = "local"
    secret_key: str = "dev-secret-key-not-for-production"
    database_url: str = "postgresql+psycopg://silk:silk@localhost:5432/silk"
    redis_url: str = "redis://localhost:6379/0"
    api_base_url: str = "http://localhost:8000"
    app_base_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"

    access_token_ttl_minutes: int = 60 * 12
    otp_ttl_minutes: int = 10

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
    coresignal_api_key: str = ""
    outscraper_api_key: str = ""
    apollo_api_key: str = ""
    zerobounce_api_key: str = ""
    smartlead_api_key: str = ""
    smartlead_webhook_secret: str = ""

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

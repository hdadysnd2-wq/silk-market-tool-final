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
    # Multi-container deploys (api + worker as separate services) MUST use object
    # storage: a local file:// image written by the api is invisible to the
    # worker. Set this to 1 on such deploys so a misconfigured local backend fails
    # loudly at startup instead of silently classifying every product text-only.
    require_object_storage: bool = False

    # Number of trusted reverse proxies in front of the API (e.g. the Railway
    # edge = 1). When > 0, the real client IP is read from X-Forwarded-For by
    # counting this many hops from the right (spoof-resistant: extra left-hand
    # entries a client injects are ignored). 0 (the default) trusts only the
    # direct peer — correct for local/CI, but behind a proxy every client shares
    # the proxy's IP, which collapses the per-IP auth throttles into one global
    # bucket (an unauthenticated login-lockout DoS). Set to 1 on Railway.
    trusted_proxy_count: int = 0
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "silk-products"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "me-south-1"

    # Vendors — blank means "use the mock adapter"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-fable-5"
    comtrade_api_key: str = ""
    # Default ON-line: the sync itself stays fail-closed (it refuses to run
    # without a real COMTRADE_API_KEY), so flipping this default cannot cause a
    # network call on keyless deploys — it only stops a by-the-book production
    # deploy from permanently disabling the world screen (audit 2026-08-07 C1).
    # Tests and hermetic lanes set COMTRADE_OFFLINE=1 explicitly.
    comtrade_offline: bool = False
    # Stage-2 market enrichment (applied tariff + PPP). Blank/False keeps the
    # deterministic mock so CI/offline stays green; True selects the LIVE World
    # Bank / WITS adapter, which routes through the engine's hardened data layer.
    market_enrichment_live: bool = False
    # Observed-price layer (paid, deepen-gated). Blank keeps the deterministic
    # MockPriceProvider so CI/offline stays green; a value selects the LIVE
    # LocalPriceProvider. This MUST be the same key the engine's LocalPriceAgent
    # reads from the environment (``LOCALPRICE_API_KEY``) — selecting the live
    # adapter on a different key would pick a provider that then finds no key and
    # returns nothing (the pre-fix SERPER_API_KEY bug).
    localprice_api_key: str = ""
    coresignal_api_key: str = ""
    outscraper_api_key: str = ""
    apollo_api_key: str = ""
    # Engine importer-intel agents (Wave 3 item 4) — the SAME env vars the
    # engine agents read (VOLZA_API_KEY / EXPLEE_API_KEY). The registry only
    # registers the providers when a key is present; the engine's PAID/deepen
    # structural guard still applies at call time.
    volza_api_key: str = ""
    explee_api_key: str = ""
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
    # a url-safe base64 32-byte key (``Fernet.generate_key()``). Only in
    # ENVIRONMENT=local may it stay blank (a key is then derived from
    # ``secret_key`` so dev/test still encrypt); everywhere else startup fails
    # without an explicit key — a SECRET_KEY rotation would otherwise silently
    # orphan every stored mailbox token.
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
    # A send claimed for egress (status ``sending``) but not resolved within this
    # many seconds is treated as interrupted and reaped (never auto-retried).
    send_claim_stale_seconds: int = 900
    # Queued-email drain (audit 2026-08-07 C4): an email still ``queued`` after
    # this many minutes is re-enqueued through the guarded send path…
    email_redispatch_minutes: int = 10
    # …and one still queued after this many hours raises a single operator
    # notification per campaign (deduplicated on the unread notification).
    email_stuck_notify_hours: int = 6
    # Celery broker visibility timeout — must exceed the longest task so Redis
    # does not redeliver a still-running task. Kept well above send/pipeline work.
    broker_visibility_timeout_seconds: int = 3600
    # An analysis left in a non-terminal status longer than this (no worker
    # progress) is reconciled to ``failed`` so the funnel never stalls silently.
    # MUST exceed one stage's worst-case wall clock — 4 executions × the 600s
    # soft limit + retry backoff ≈ 41 min — or the reaper kills legitimately
    # long live-vendor runs (symptom B). Stage loops also heartbeat the row per
    # market (services.heartbeat), so a healthy run is never stale regardless.
    analysis_stuck_minutes: int = 50
    # world_trade (Stage-1 screening data) coverage refresh: a confirmed HS6 whose
    # rows are older than this is re-synced from UN Comtrade by the scheduled sweep.
    # The per-HS6 live sync is fail-closed on a real COMTRADE key (offline demos
    # never pretend to have live coverage).
    world_trade_refresh_days: int = 30
    # Hard/soft ceilings on any single Celery task, so a hung vendor/LLM call
    # cannot occupy a worker slot forever.
    task_soft_time_limit_seconds: int = 600
    task_time_limit_seconds: int = 660

    # Deliverability guardrails
    max_emails_per_inbox_per_day: int = 50
    warmup_days: int = 14
    bounce_rate_pause_threshold: float = 0.05
    complaint_rate_pause_threshold: float = 0.001

    # Mock behaviour (kept deterministic for demos and tests)
    mock_seed: int = 42
    mock_emit_engagement: bool = True
    # Outside ENVIRONMENT=local the sending/mailbox slots refuse to fall back to
    # the mocks (an email a mock "sent" reached nobody while the row said sent).
    # This is the one explicit escape hatch — a keyless staging demo sets it
    # knowingly; production never should.
    allow_mock_sending: bool = False
    # Same rule for DATA slots that would otherwise fabricate client-visible
    # figures (observed prices, Stage-2 tariff/PPP): outside local they fail
    # closed to declared gaps unless a keyless staging demo opts in knowingly
    # (audit 2026-08-07 C3). Production never should.
    allow_mock_data: bool = False

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

    @model_validator(mode="after")
    def _require_token_key_outside_local(self) -> Settings:
        """Fail closed if TOKEN_ENCRYPTION_KEY is blank outside local.

        The keyless fallback derives the Fernet key from SECRET_KEY, which ties
        every stored mailbox OAuth token to the signing secret: rotating
        SECRET_KEY (routine hygiene) would silently orphan them all. Local
        dev/CI keep the convenience fallback; staging/prod must set an explicit
        key so the two secrets rotate independently.
        """
        if self.environment.strip().lower() != "local" and not self.token_encryption_key.strip():
            raise ValueError(
                f"TOKEN_ENCRYPTION_KEY is unset but ENVIRONMENT={self.environment!r} "
                "is not 'local'. Generate one with "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())" and set it — it encrypts '
                "mailbox OAuth tokens at rest, independently of SECRET_KEY."
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

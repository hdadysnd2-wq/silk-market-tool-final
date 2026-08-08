"""Application settings.

Every external vendor is optional: a blank key means the provider registry
selects the deterministic mock adapter instead, so the platform runs end to end
with no third-party accounts.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET_DEFAULT = "dev-secret-key-not-for-production"

# The three spellings of the loopback host. In local dev they name the same
# machine, but ``http://localhost:3000`` and ``http://127.0.0.1:3000`` are
# *different* browser origins — a mismatch that otherwise 403s every
# state-changing request with "Cross-origin request blocked". Treated as
# interchangeable for the trusted-origin set in local only.
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _canonical_origin(url: str) -> str | None:
    """Canonical ``scheme://host[:port]`` for an origin/URL, or ``None``.

    Normalizes an operator-supplied origin (or a full URL like ``APP_BASE_URL``)
    to exactly the shape a browser puts in its ``Origin`` header, so the CSRF
    check can compare by equality without tripping over spelling differences:

    - drops any path / query / fragment (``https://app.example.com/`` → origin);
    - lowercases scheme and host (``https://App.Example.com`` → lowercase);
    - drops a *default* port (``:80`` for http, ``:443`` for https) — a browser
      never puts the default port in ``Origin``, but an operator might;
    - re-brackets IPv6 literals.

    Scheme is preserved verbatim (``http`` ≠ ``https``): an ``http://`` entry for
    an https-served site must fail loudly, not be silently upgraded. Returns
    ``None`` for anything without a scheme+host (e.g. ``"*"`` or ``Origin: null``).
    """
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname  # already lowercased; strips IPv6 brackets
        if not parts.scheme or not host:
            return None
        scheme = parts.scheme.lower()
        try:
            port = parts.port  # raises ValueError on a non-numeric port
        except ValueError:
            return None
    except ValueError:
        return None
    if port is not None and str(port) == _DEFAULT_PORTS.get(scheme):
        port = None
    if ":" in host:  # IPv6 literal — urlsplit strips the brackets, re-add them
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return f"{scheme}://{netloc}"


def _loopback_equivalents(origins: list[str]) -> list[str]:
    """Expand any loopback origin to all three loopback spellings (same port).

    ``http://localhost:3000`` → also ``http://127.0.0.1:3000`` and
    ``http://[::1]:3000``. Non-loopback origins pass through untouched.
    """
    out = list(origins)
    for origin in origins:
        parts = urlsplit(origin)
        if parts.hostname not in _LOOPBACK_HOSTS:
            continue
        port = f":{parts.port}" if parts.port else ""
        for host in ("localhost", "127.0.0.1", "[::1]"):
            candidate = f"{parts.scheme}://{host}{port}"
            if candidate not in out:
                out.append(candidate)
    return out


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
    # Volza data-API base URL. The paid host/path can differ per subscription
    # plan (the engine's silk_volza_agent reads the same env var for the same
    # reason); the shipments adapter appends its endpoint paths to this base.
    volza_api_url: str = "https://api.volza.com/v1"
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
    # Outside local, /metrics requires this bearer token; unset → the endpoint
    # 404s (never an open Prometheus scrape surface). Local is always open.
    metrics_token: str = ""

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

    @model_validator(mode="after")
    def _safe_prod_networking_defaults(self) -> Settings:
        """Fail closed on the two unsafe defaults the audit flagged (H7).

        Outside local:
        - ``trusted_proxy_count == 0`` behind an edge proxy collapses the per-IP
          login throttle into ONE global bucket → 20 junk logins lock everyone
          out. Any real deploy sits behind ≥1 proxy, so 0 is never right there.
        - ``api_base_url`` still at the localhost default means every outbound
          email embeds a localhost unsubscribe link — an RFC 8058 / compliance
          break on the money path.
        Local/CI keep the convenient defaults.

        NB: ``app_base_url`` is deliberately NOT a fail-closed guard here. It is
        imported at boot by every backend role (api/worker/beat all build
        ``Settings`` — the worker via ``celery_app``), so a fatal check on it
        would crash-loop the whole platform when the variable is merely missing
        on one service. A wrong/localhost ``app_base_url`` only weakens the CSRF
        escape hatch (writes still work off ``CORS_ORIGINS``) and mis-points
        OAuth return links — degraded, not down. The ``csrf_origin_blocked`` log
        surfaces the mismatch without taking the service offline.
        """
        if self.environment.strip().lower() == "local":
            return self
        if self.trusted_proxy_count < 1:
            raise ValueError(
                f"TRUSTED_PROXY_COUNT={self.trusted_proxy_count} but "
                f"ENVIRONMENT={self.environment!r} is not 'local'. A real deploy "
                "sits behind at least one reverse proxy; 0 makes the per-IP login "
                "throttle a global lockout (20 bad logins lock out everyone). Set "
                "it to the number of trusted proxies in front of the API (Railway "
                "edge = 1)."
            )
        if "localhost" in self.api_base_url or "127.0.0.1" in self.api_base_url:
            raise ValueError(
                f"API_BASE_URL={self.api_base_url!r} still points at localhost but "
                f"ENVIRONMENT={self.environment!r} is not 'local'. Every outbound "
                "email embeds its unsubscribe link under this origin; a localhost "
                "link is a dead unsubscribe (RFC 8058 / compliance break). Set it "
                "to the API's public URL."
            )
        return self

    @model_validator(mode="after")
    def _reject_wildcard_cors_outside_local(self) -> Settings:
        """Fail closed on a credentialed wildcard CORS origin outside local.

        The app serves cookie/Bearer-authenticated tenant PII and mounts CORS with
        ``allow_credentials=True``. Starlette, given ``*`` with credentials on,
        reflects the caller's Origin and returns ``Access-Control-Allow-Credentials:
        true`` — i.e. ANY site can read a logged-in user's authenticated responses.
        Outside local we require an explicit, non-wildcard allowlist. Local/CI keep
        the convenient ``http://localhost:3000`` default.
        """
        if self.environment.strip().lower() == "local":
            return self
        origins = self.cors_origin_list
        if not origins or "*" in origins:
            raise ValueError(
                f"CORS_ORIGINS={self.cors_origins!r} is empty or contains '*' but "
                f"ENVIRONMENT={self.environment!r} is not 'local'. The API mounts "
                "credentialed CORS, so a wildcard lets any site read authenticated "
                "tenant data cross-origin. Set an explicit comma-separated allowlist "
                "of exact origins (e.g. https://app.example.com)."
            )
        return self

    @model_validator(mode="after")
    def _reject_default_s3_creds_outside_local(self) -> Settings:
        """Fail closed if S3 is enabled with the built-in MinIO dev credentials.

        ``minioadmin/minioadmin`` is the public MinIO default; a deploy that flips
        ``storage_backend=s3`` without overriding the keys would run object storage
        on well-known credentials. Only enforced when S3 is actually selected;
        local dev/CI (and the default ``local`` backend) keep the convenience keys.
        """
        if self.environment.strip().lower() == "local":
            return self
        if self.storage_backend.strip().lower() == "s3" and (
            self.s3_access_key == "minioadmin" or self.s3_secret_key == "minioadmin"
        ):
            raise ValueError(
                f"STORAGE_BACKEND=s3 with ENVIRONMENT={self.environment!r} but the "
                "S3 credentials are still the built-in MinIO dev default "
                "('minioadmin'). Set real S3_ACCESS_KEY / S3_SECRET_KEY."
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_origins(self) -> list[str]:
        """First-party origins trusted for CORS *and* the cookie-CSRF check.

        The web app talks to one origin (the browser hits the Next.js server,
        which proxies ``/api/v1/*`` to this API), so a state-changing request
        arrives carrying the *web* app's ``Origin``. The cookie-CSRF guard pins
        that Origin to this set; if it isn't in it, the request 403s with
        "Cross-origin request blocked".

        The set is the union of the explicit ``CORS_ORIGINS`` allowlist and
        ``APP_BASE_URL``'s own origin. Folding ``APP_BASE_URL`` in means an
        operator who moves the web app to a custom domain only has to update the
        one variable they must set anyway (email/OAuth links are built from it,
        and a prod guard forbids it pointing at localhost) — a stale
        ``CORS_ORIGINS`` no longer silently blocks every write. In local, the
        loopback spellings (localhost / 127.0.0.1 / [::1]) are treated as
        interchangeable so hitting the dev server on 127.0.0.1 isn't blocked.

        Every entry is **canonicalized** (``_canonical_origin``: origin-only,
        lowercased host, default port dropped) so a config value that differs
        from the browser's ``Origin`` only by a trailing slash, host case, or an
        explicit ``:443`` still matches — the most common operator mistakes. The
        CSRF guard canonicalizes the incoming ``Origin`` the same way, so both
        sides of the comparison are normal-form. Scheme stays significant.

        A wildcard is only reachable in local (the prod guard rejects it); it is
        returned verbatim so Starlette's own ``*`` handling still applies.
        """
        origins: list[str] = []
        for raw in [*self.cors_origin_list, self.app_base_url]:
            if raw == "*":
                origins.append("*")
                continue
            canon = _canonical_origin(raw)
            if canon:
                origins.append(canon)
        if "*" in origins:
            return origins
        if self.environment.strip().lower() == "local":
            origins = _loopback_equivalents(origins)
        # De-duplicate while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for origin in origins:
            if origin not in seen:
                seen.add(origin)
                deduped.append(origin)
        return deduped


@lru_cache
def get_settings() -> Settings:
    return Settings()

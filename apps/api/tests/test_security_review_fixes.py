"""Regression locks for the 2026-08 security review fixes.

Covers: credentialed-wildcard CORS guard, default-S3-credential guard, the
cookie-auth CSRF Origin check, sending-domain hostname validation, and the
log-safe rendering of provider HTTP errors (no query-string API-key leak).
"""

from __future__ import annotations

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.providers.http_errors import redact_secrets, safe_error
from app.services import dns_check

_STRONG_SECRET = "a-strong-production-secret-key-32-bytes!"


def _prod_kwargs(**overrides) -> dict:
    """Baseline kwargs that satisfy every OTHER prod startup guard, so a test can
    isolate the one validator under test by overriding a single field."""
    base = {
        "environment": "production",
        "secret_key": _STRONG_SECRET,
        "token_encryption_key": Fernet.generate_key().decode(),
        "trusted_proxy_count": 1,
        "api_base_url": "https://api.silk.example",
        "app_base_url": "https://app.silk.example",
        "cors_origins": "https://app.silk.example",
    }
    base.update(overrides)
    return base


# -- CORS credentialed-wildcard guard --------------------------------------


def test_wildcard_cors_rejected_outside_local():
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(**_prod_kwargs(cors_origins="*"))


def test_empty_cors_rejected_outside_local():
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(**_prod_kwargs(cors_origins=""))


def test_explicit_cors_allowlist_constructs():
    settings = Settings(
        **_prod_kwargs(cors_origins="https://app.silk.example,https://admin.silk.example")
    )
    assert settings.cors_origin_list == [
        "https://app.silk.example",
        "https://admin.silk.example",
    ]


def test_wildcard_cors_allowed_in_local():
    # Local dev keeps the convenience; the guard only bites outside local.
    settings = Settings(environment="local", cors_origins="*")
    assert settings.cors_origin_list == ["*"]


# -- trusted_origins: APP_BASE_URL backfill + local loopback equivalence -----


def test_trusted_origins_includes_app_base_url_origin():
    # A web app moved to a custom domain (set in APP_BASE_URL) stays trusted even
    # if CORS_ORIGINS still holds the old origin — no "Cross-origin request
    # blocked" 403 on every write from config drift.
    settings = Settings(
        **_prod_kwargs(
            cors_origins="https://legacy.silk.example",
            app_base_url="https://app.silk.example/onboarding",  # a full URL folds to its origin
        )
    )
    assert "https://app.silk.example" in settings.trusted_origins
    assert "https://legacy.silk.example" in settings.trusted_origins


def test_trusted_origins_loopback_equivalent_in_local():
    # localhost / 127.0.0.1 / [::1] name the same dev machine but are distinct
    # browser origins — treat them as one so 127.0.0.1 isn't blocked.
    settings = Settings(
        environment="local",
        cors_origins="http://localhost:3000",
        app_base_url="http://localhost:3000",
    )
    trusted = settings.trusted_origins
    assert "http://localhost:3000" in trusted
    assert "http://127.0.0.1:3000" in trusted
    assert "http://[::1]:3000" in trusted


def test_trusted_origins_no_loopback_expansion_outside_local():
    # Real deploys aren't on loopback; don't synthesize extra origins there.
    settings = Settings(
        **_prod_kwargs(
            cors_origins="https://app.silk.example",
            app_base_url="https://app.silk.example",
        )
    )
    assert settings.trusted_origins == ["https://app.silk.example"]


def test_trusted_origins_wildcard_passthrough_in_local():
    # A wildcard survives only in local; return it verbatim for Starlette's "*".
    settings = Settings(environment="local", cors_origins="*")
    assert "*" in settings.trusted_origins


def test_trusted_origins_canonicalizes_config_spellings():
    # Trailing slash, uppercase host, and an explicit :443 are the most common
    # operator mistakes — all must fold to the exact origin a browser sends.
    settings = Settings(
        **_prod_kwargs(
            cors_origins="https://App.Silk.Example/,https://admin.silk.example:443",
            app_base_url="https://app.silk.example",
        )
    )
    assert "https://app.silk.example" in settings.trusted_origins
    assert "https://admin.silk.example" in settings.trusted_origins
    # No un-canonical spelling leaks into the allowlist.
    assert "https://App.Silk.Example/" not in settings.trusted_origins
    assert "https://admin.silk.example:443" not in settings.trusted_origins


def test_canonical_origin_normalization_units():
    from app.config import _canonical_origin

    assert _canonical_origin("https://app.example.com/") == "https://app.example.com"
    assert _canonical_origin("https://App.Example.COM") == "https://app.example.com"
    assert _canonical_origin("https://app.example.com:443/x?y=1") == "https://app.example.com"
    assert _canonical_origin("http://app.example.com:80") == "http://app.example.com"
    assert _canonical_origin("http://app.example.com:8080") == "http://app.example.com:8080"
    assert _canonical_origin("http://[::1]:3000") == "http://[::1]:3000"
    # Not an origin → None (so "*" and Origin: null are never trusted).
    assert _canonical_origin("null") is None
    assert _canonical_origin("*") is None
    assert _canonical_origin("") is None
    # Scheme stays significant: http never folds into an https allowlist.
    assert _canonical_origin("http://app.example.com") != _canonical_origin(
        "https://app.example.com"
    )


# -- S3 default-credential guard -------------------------------------------


def test_default_s3_creds_rejected_when_s3_backend_outside_local():
    with pytest.raises(ValueError, match="minioadmin|MinIO"):
        Settings(**_prod_kwargs(storage_backend="s3"))


def test_overridden_s3_creds_construct():
    settings = Settings(
        **_prod_kwargs(storage_backend="s3", s3_access_key="AKIAREAL", s3_secret_key="realsecret")
    )
    assert settings.s3_access_key == "AKIAREAL"


def test_default_s3_creds_ok_with_local_storage_backend():
    # The default 'local' backend never touches S3, so the default keys are fine.
    settings = Settings(**_prod_kwargs(storage_backend="local"))
    assert settings.storage_backend == "local"


# -- sending-domain hostname validation ------------------------------------


@pytest.mark.parametrize(
    "domain",
    ["example.com", "mail.factory-export.com", "a.b.c.co.uk", "xn--80ak6aa92e.com"],
)
def test_valid_domains(domain):
    assert dns_check.is_valid_domain(domain)


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "not a domain",
        "http://example.com",
        "example.com/path",
        "example.com:53",
        "-leadinghyphen.com",
        "nodot",
        "under_score.com",
    ],
)
def test_invalid_domains(domain):
    assert not dns_check.is_valid_domain(domain)


# -- provider HTTP error rendering never leaks the query-string key --------


def test_safe_error_status_only_for_http_status_error():
    request = httpx.Request("GET", "https://api.vendor.example/v2/x?api_key=SUPERSECRET")
    response = httpx.Response(401, request=request)
    exc = httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)
    rendered = safe_error(exc)
    assert rendered == "HTTP 401"
    assert "SUPERSECRET" not in rendered
    assert "api_key" not in rendered


def test_safe_error_scrubs_key_from_transport_error_text():
    exc = httpx.ConnectError("failed for url https://v.example/x?api_key=SUPERSECRET&email=a@b.c")
    rendered = safe_error(exc)
    assert "SUPERSECRET" not in rendered
    assert "ConnectError" in rendered


def test_safe_error_handles_response_none():
    # A hand-built HTTPStatusError with no response must not crash.
    exc = httpx.HTTPStatusError("500", request=None, response=None)
    assert safe_error(exc) == "HTTPStatusError"


def test_redact_secrets_masks_common_credential_keys():
    scrubbed = redact_secrets("?api_key=abc123&token=def456&email=a@b.c")
    assert "abc123" not in scrubbed
    assert "def456" not in scrubbed
    assert "email=a@b.c" in scrubbed  # non-secret params are preserved


# -- CSRF Origin check for cookie-authenticated state-changing requests -----


def _cookie(client, factory_user):
    from app.security import create_access_token

    client.cookies.set("silk_token", create_access_token(factory_user.id, factory_user.role))


def test_cookie_put_without_origin_is_blocked(client, factory_user):
    _cookie(client, factory_user)
    res = client.put("/api/v1/auth/me", json={"display_name": "X"})
    assert res.status_code == 403, res.text


def test_cookie_put_with_foreign_origin_is_blocked(client, factory_user):
    _cookie(client, factory_user)
    res = client.put(
        "/api/v1/auth/me",
        json={"display_name": "X"},
        headers={"Origin": "https://evil.example"},
    )
    assert res.status_code == 403, res.text


def test_cookie_put_with_allowed_origin_succeeds(client, factory_user):
    _cookie(client, factory_user)
    res = client.put(
        "/api/v1/auth/me",
        json={"display_name": "X"},
        headers={"Origin": "http://localhost:3000"},  # the local CORS allowlist
    )
    assert res.status_code == 200, res.text


def test_cookie_put_with_loopback_origin_succeeds(client, factory_user):
    # The dev server allowlists http://localhost:3000; a browser that reached it
    # via http://127.0.0.1:3000 sends that loopback Origin. In local the two are
    # treated as the same origin, so the write is NOT blocked.
    _cookie(client, factory_user)
    res = client.put(
        "/api/v1/auth/me",
        json={"display_name": "X"},
        headers={"Origin": "http://127.0.0.1:3000"},
    )
    assert res.status_code == 200, res.text


def _fake_put_request(headers: dict[str, str]):
    from starlette.requests import Request

    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": "/api/v1/auth/me",
        "raw_path": b"/api/v1/auth/me",
        "query_string": b"",
        "root_path": "",
        "headers": raw,
        "server": ("testserver", 80),
        "client": ("test", 123),
    }
    return Request(scope)


def test_local_wildcard_origin_accepts_any_origin(monkeypatch):
    # In local a wildcard CORS_ORIGINS trusts every origin for the CSRF guard too
    # (matches the CORS middleware's "*" behaviour); prod rejects the wildcard.
    from app import security

    monkeypatch.setattr(
        security, "get_settings", lambda: Settings(environment="local", cors_origins="*")
    )
    # No exception raised => accepted.
    security._enforce_same_origin(_fake_put_request({"origin": "https://anything.example"}))


def test_foreign_origin_still_blocked_via_guard(monkeypatch):
    from fastapi import HTTPException

    from app import security

    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: Settings(environment="local", cors_origins="http://localhost:3000"),
    )
    with pytest.raises(HTTPException) as exc:
        security._enforce_same_origin(_fake_put_request({"origin": "https://evil.example"}))
    assert exc.value.status_code == 403


def test_guard_matches_despite_config_trailing_slash_and_case(monkeypatch):
    # The browser always sends a bare, lowercase Origin. A CORS_ORIGINS spelled
    # with a trailing slash / uppercase host must still match after canonicalizing
    # both sides — this is the exact class of prod 403 the fix targets.
    from app import security

    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: Settings(
            **_prod_kwargs(
                cors_origins="https://App.Silk.Example/", app_base_url="https://app.silk.example"
            )
        ),
    )
    # No exception => accepted.
    security._enforce_same_origin(_fake_put_request({"origin": "https://app.silk.example"}))


def test_guard_keeps_scheme_significant(monkeypatch):
    # Canonicalization must NOT upgrade http→https: an http allowlist entry for an
    # https-served site fails loudly rather than silently matching.
    from fastapi import HTTPException

    from app import security

    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: Settings(
            **_prod_kwargs(
                cors_origins="http://app.silk.example", app_base_url="http://app.silk.example"
            )
        ),
    )
    with pytest.raises(HTTPException) as exc:
        security._enforce_same_origin(_fake_put_request({"origin": "https://app.silk.example"}))
    assert exc.value.status_code == 403


def test_cookie_get_is_not_csrf_checked(client, factory_user):
    # Safe methods are exempt — a browser GET carries no CSRF risk.
    _cookie(client, factory_user)
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200, res.text


def test_bearer_put_is_not_csrf_checked(client, auth_headers):
    # An explicit Bearer header can't be set cross-site, so no Origin is required.
    res = client.put("/api/v1/auth/me", json={"display_name": "X"}, headers=auth_headers)
    assert res.status_code == 200, res.text

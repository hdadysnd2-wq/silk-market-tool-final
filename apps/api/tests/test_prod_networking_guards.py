"""Lock the fail-loud production networking defaults (audit 2026-08-07 H7)."""

from __future__ import annotations

import pytest

from app.config import Settings

_BASE = {
    "secret_key": "x" * 40,
    "token_encryption_key": "t" * 44,
}


def _prod(**over) -> dict:
    d = dict(_BASE)
    d.update(
        environment="production",
        trusted_proxy_count=1,
        api_base_url="https://api.silk.example",
        app_base_url="https://app.silk.example",
    )
    d.update(over)
    return d


def test_prod_rejects_zero_trusted_proxy_count():
    with pytest.raises(ValueError, match="TRUSTED_PROXY_COUNT"):
        Settings(**_prod(trusted_proxy_count=0))


def test_prod_rejects_localhost_api_base_url():
    with pytest.raises(ValueError, match="API_BASE_URL"):
        Settings(**_prod(api_base_url="http://localhost:8000"))


def test_prod_rejects_localhost_app_base_url():
    # APP_BASE_URL is the canonical web origin AND is folded into the CSRF
    # trusted-origin set; a localhost value in prod is a dead link origin and
    # neuters the "just set APP_BASE_URL for a custom domain" escape hatch.
    with pytest.raises(ValueError, match="APP_BASE_URL"):
        Settings(**_prod(app_base_url="http://localhost:3000"))


def test_prod_accepts_safe_values():
    s = Settings(**_prod())
    assert s.trusted_proxy_count == 1
    assert "localhost" not in s.api_base_url


def test_local_keeps_convenient_defaults():
    s = Settings(environment="local", **_BASE)
    assert s.trusted_proxy_count == 0
    assert "localhost" in s.api_base_url

"""Regression locks: TOKEN_ENCRYPTION_KEY is mandatory outside local (Wave 2 item 2).

The keyless SHA256(SECRET_KEY) Fernet fallback is a dev/test convenience only.
In production it silently couples every stored mailbox OAuth token to the
signing secret, so a routine SECRET_KEY rotation would orphan them all. The
settings validator rejects a blank key at startup outside ``local``, and
``crypto._fernet`` refuses the derived fallback as defense in depth.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app import crypto
from app.config import Settings

_STRONG_SECRET = "a-strong-production-secret-key-32-bytes!"


def test_prod_settings_without_token_key_fail_startup():
    with pytest.raises(ValueError, match="TOKEN_ENCRYPTION_KEY"):
        Settings(environment="production", secret_key=_STRONG_SECRET, token_encryption_key="")


def test_prod_settings_with_token_key_construct():
    settings = Settings(
        environment="production",
        secret_key=_STRONG_SECRET,
        token_encryption_key=Fernet.generate_key().decode(),
        trusted_proxy_count=1,
        api_base_url="https://api.silk.example",
        app_base_url="https://app.silk.example",
    )
    assert settings.token_encryption_key


def test_local_keyless_roundtrip_still_works():
    # The suite runs with ENVIRONMENT=local and no key — the derived-key
    # convenience path must keep encrypting for dev/test.
    assert crypto.decrypt(crypto.encrypt("refresh-token")) == "refresh-token"


def test_fernet_refuses_derived_fallback_outside_local(monkeypatch):
    # model_construct bypasses validators — simulating a code path that builds
    # Settings around the startup guard. _fernet must still refuse.
    rogue = Settings.model_construct(
        environment="production", secret_key=_STRONG_SECRET, token_encryption_key=""
    )
    monkeypatch.setattr(crypto, "get_settings", lambda: rogue)
    crypto._fernet.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
            crypto._fernet()
    finally:
        crypto._fernet.cache_clear()

"""Reversible encryption for secrets stored at rest (OAuth tokens).

OAuth access/refresh tokens are stored encrypted, never in plaintext — a leaked
database dump must not hand an attacker the ability to send mail as a factory's
mailbox. Encryption is symmetric (Fernet / AES-128-CBC + HMAC).

The key comes from ``settings.token_encryption_key`` (a url-safe base64 32-byte
Fernet key). Only in ENVIRONMENT=local — dev, CI, tests — may it be blank, in
which case a key is derived deterministically from ``secret_key`` so the whole
flow still encrypts without extra configuration. Everywhere else the settings
validator rejects a blank key at startup, and ``_fernet`` refuses the derived
fallback as defense in depth: rotating ``secret_key`` would otherwise silently
orphan every stored token.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings


class TokenDecryptError(Exception):
    """Raised when a stored ciphertext cannot be decrypted (wrong/rotated key)."""


def _derive_key(secret_key: str) -> bytes:
    """A stable Fernet key from an arbitrary secret, for keyless dev/test use."""
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache
def _fernet() -> Fernet:
    settings: Settings = get_settings()
    key = settings.token_encryption_key.strip()
    if key:
        # Accept a raw 32-byte base64 Fernet key as-is; anything else is hashed
        # into one so a human-chosen passphrase still yields a valid key.
        try:
            Fernet(key.encode("utf-8"))
            key_bytes = key.encode("utf-8")
        except (ValueError, TypeError):
            key_bytes = _derive_key(key)
    else:
        if settings.environment.strip().lower() != "local":
            # The settings validator already rejects this at startup; refuse
            # here too so no code path can encrypt with the derived key in prod.
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY is required outside ENVIRONMENT=local; "
                "refusing the SECRET_KEY-derived fallback."
            )
        key_bytes = _derive_key(settings.secret_key)
    return Fernet(key_bytes)


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a secret. ``None`` passes through (no token to store)."""
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a stored secret. ``None`` passes through."""
    if ciphertext is None:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise TokenDecryptError("stored token could not be decrypted") from exc

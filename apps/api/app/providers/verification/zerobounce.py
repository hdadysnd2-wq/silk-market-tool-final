"""ZeroBounce email verification adapter."""

from __future__ import annotations

import httpx

from app.logging import get_logger
from app.providers.base import VerificationOutcome, VerificationResult

log = get_logger(__name__)

ZEROBOUNCE_URL = "https://api.zerobounce.net/v2/validate"

_STATUS_MAP = {
    "valid": VerificationOutcome.valid,
    "catch-all": VerificationOutcome.risky,
    "unknown": VerificationOutcome.unknown,
    "invalid": VerificationOutcome.invalid,
    "spamtrap": VerificationOutcome.invalid,
    "abuse": VerificationOutcome.invalid,
    "do_not_mail": VerificationOutcome.invalid,
}


class ZeroBounceVerifier:
    name = "zerobounce"

    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def verify(self, email: str) -> VerificationResult:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(
                    ZEROBOUNCE_URL, params={"api_key": self._api_key, "email": email}
                )
                response.raise_for_status()
                status = response.json().get("status", "unknown")
        # Degrade on ANY failure — a network error, a non-JSON body, or an
        # unexpected shape — to the safe outcome, never crash the caller (I1).
        # `unknown` is not sendable, so a hiccup can never leak an unverified send.
        except Exception as exc:
            log.warning("zerobounce_failed", email=email, error=str(exc))
            return VerificationResult(
                email=email, outcome=VerificationOutcome.unknown, provider_name=self.name
            )
        return VerificationResult(
            email=email,
            outcome=_STATUS_MAP.get(status, VerificationOutcome.unknown),
            provider_name=self.name,
        )

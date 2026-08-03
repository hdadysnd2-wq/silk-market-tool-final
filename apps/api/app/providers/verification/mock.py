"""Deterministic email verifier stand-in (ZeroBounce/NeverBounce-shaped)."""

from __future__ import annotations

from app.providers.base import VerificationOutcome, VerificationResult
from app.providers.determinism import rng_for


class MockEmailVerifier:
    name = "mock_zerobounce"

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def verify(self, email: str) -> VerificationResult:
        # Obvious junk fails outright regardless of the seed.
        if "@" not in email or email.count("@") != 1 or email.startswith("@"):
            return VerificationResult(
                email=email, outcome=VerificationOutcome.invalid, provider_name=self.name
            )

        rng = rng_for(email.lower(), self._seed)
        roll = rng.random()
        # Weighted to keep the sendable pool healthy: ~70% valid, ~18% risky,
        # ~10% invalid, ~2% unknown. Generic mailboxes skew riskier.
        if email.split("@", 1)[0] in {"info", "contact", "sales"}:
            outcome = VerificationOutcome.risky if roll < 0.75 else VerificationOutcome.invalid
        elif roll < 0.70:
            outcome = VerificationOutcome.valid
        elif roll < 0.88:
            outcome = VerificationOutcome.risky
        elif roll < 0.98:
            outcome = VerificationOutcome.invalid
        else:
            outcome = VerificationOutcome.unknown
        return VerificationResult(email=email, outcome=outcome, provider_name=self.name)

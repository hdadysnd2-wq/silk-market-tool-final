"""Email-finding waterfall: primary finder → pattern guess → verification.

Only addresses that verify as valid or risky survive; invalid and unknown are
dropped so the stored contact set stays under the 5% bounce target.
"""

from __future__ import annotations

from app.logging import get_logger
from app.providers.base import (
    EmailFinderProvider,
    EmailVerifier,
    FoundContact,
    ProviderRecord,
    SourceType,
)

log = get_logger(__name__)


class EmailFindingWaterfall:
    """Compose a finder and a verifier into the spec's waterfall."""

    def __init__(self, finder: EmailFinderProvider, verifier: EmailVerifier) -> None:
        self._finder = finder
        self._verifier = verifier

    def resolve(self, company_name: str, domain: str | None, country_iso2: str) -> list[dict]:
        """Return verified contacts as plain dicts ready for persistence."""
        found = self._finder.find_contacts(company_name, domain, country_iso2)

        if not found and domain:
            found = [self._pattern_guess(company_name, domain)]

        verified: list[dict] = []
        for record in found:
            contact = record.data
            result = self._verifier.verify(contact.email)
            if not result.is_sendable:
                log.info(
                    "contact_rejected_verification",
                    email=contact.email,
                    outcome=result.outcome.value,
                )
                continue
            verified.append(
                {
                    "email": contact.email,
                    "full_name": contact.full_name,
                    "title": contact.title,
                    "found_via": contact.found_via,
                    "verification_status": result.outcome.value,
                    "confidence": record.confidence,
                    "source": record.source.value,
                }
            )
        return verified

    @staticmethod
    def _pattern_guess(company_name: str, domain: str) -> ProviderRecord[FoundContact]:
        """Last-resort generic address when no contact could be found."""
        return ProviderRecord(
            data=FoundContact(
                email=f"info@{domain}",
                full_name=None,
                title=None,
                found_via="pattern_guess",
            ),
            source=SourceType.MANUAL,
            provider_name="pattern_guess",
            confidence=0.3,
        )

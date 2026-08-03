"""Source-agnostic provider contracts.

Every external data vendor and every LLM sits behind one of the Protocols in
this module, so swapping Coresignal for Volza, or Anthropic for another model
host, is an adapter change rather than a refactor. Adapters never touch the
database; services translate ``ProviderRecord`` envelopes into rows.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Generic, Protocol, TypeVar

from app.models.base import utcnow

T = TypeVar("T")


class SourceType(str, enum.Enum):
    """Where a record came from, in descending order of buy-intent strength."""

    CUSTOMS = "customs"
    COMTRADE = "comtrade"
    ENRICHMENT = "enrichment"
    MAPS = "maps"
    MANUAL = "manual"


#: Relative trust per source, consumed by the relevance scorer. Customs data is
#: an observed transaction; a Maps listing is only an indication of business type.
SOURCE_QUALITY: dict[SourceType, float] = {
    SourceType.CUSTOMS: 1.0,
    SourceType.COMTRADE: 0.7,
    SourceType.ENRICHMENT: 0.55,
    SourceType.MAPS: 0.35,
    SourceType.MANUAL: 0.6,
}


@dataclass(frozen=True)
class ProviderRecord(Generic[T]):
    """A payload plus its provenance.

    Provenance travels with the data all the way to the database so every buyer
    row can answer "who told us this, how sure are they, and how stale is it".
    """

    data: T
    source: SourceType
    provider_name: str
    confidence: float
    fetched_at: datetime = field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Payload types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeFlow:
    """Aggregate import value of one HS code into one market for one year."""

    hs_code: str
    importer_iso2: str
    year: int
    value_usd: float
    quantity: float | None = None
    partner_iso2: str | None = None


@dataclass(frozen=True)
class ExporterShare:
    """One origin country's share of a market's imports for an HS code."""

    exporter_iso2: str
    exporter_name: str
    value_usd: float
    share_pct: float
    year: int


@dataclass(frozen=True)
class ShipmentRecord:
    """A single customs / bill-of-lading movement."""

    consignee_name: str
    hs_code: str
    origin_iso2: str
    dest_iso2: str
    shipment_date: date
    value_usd: float | None = None
    quantity: float | None = None
    quantity_unit: str | None = None
    shipper_name: str | None = None
    external_id: str | None = None
    consignee_city: str | None = None


@dataclass(frozen=True)
class CompanyFirmographics:
    name: str
    country_iso2: str
    domain: str | None = None
    website: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    city: str | None = None
    revenue_band: str | None = None
    #: Procurement / import decision-makers, when the vendor exposes them.
    key_people: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class MapsPlace:
    name: str
    country_iso2: str
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    city: str | None = None


@dataclass(frozen=True)
class FoundContact:
    email: str
    full_name: str | None = None
    title: str | None = None
    #: How the address was obtained, e.g. "apollo" or "pattern_guess".
    found_via: str = "unknown"


class VerificationOutcome(str, enum.Enum):
    valid = "valid"
    risky = "risky"
    invalid = "invalid"
    unknown = "unknown"


@dataclass(frozen=True)
class VerificationResult:
    email: str
    outcome: VerificationOutcome
    provider_name: str
    checked_at: datetime = field(default_factory=utcnow)

    @property
    def is_sendable(self) -> bool:
        """Only verified-good addresses may be stored for sending.

        ``risky`` passes because catch-all domains are common in B2B, but
        ``invalid``/``unknown`` are rejected to keep bounce rate under 5%.
        """
        return self.outcome in (VerificationOutcome.valid, VerificationOutcome.risky)


@dataclass(frozen=True)
class OutboundEmail:
    """Everything the sending infrastructure needs for one message."""

    to_email: str
    to_name: str | None
    subject: str
    body_text: str
    body_html: str | None
    from_name: str
    from_email: str
    reply_to: str | None
    sending_domain: str | None
    unsubscribe_url: str
    campaign_ref: str
    message_ref: str


@dataclass(frozen=True)
class SendResult:
    accepted: bool
    provider_message_id: str | None
    provider_name: str
    error: str | None = None


# --------------------------------------------------------------------------
# Per-tenant mailbox (OAuth) sending
# --------------------------------------------------------------------------


class TokenRefreshError(Exception):
    """Raised when a refresh token is revoked or expired and cannot be renewed.

    The caller responds by pausing the account's campaigns, marking the account
    ``needs_reauth`` and notifying the factory — never by failing silently.
    """


class MailboxVerificationError(Exception):
    """Raised when a freshly connected mailbox cannot be verified before use."""


@dataclass(frozen=True)
class OAuthTokens:
    """The result of an OAuth code exchange or refresh."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: str | None = None


@dataclass(frozen=True)
class MailboxCredentials:
    """Decrypted, ready-to-use credentials for one connected mailbox."""

    email: str
    access_token: str
    refresh_token: str | None = None
    token_expires_at: datetime | None = None


@dataclass(frozen=True)
class MailboxIdentity:
    """Who the connected mailbox actually belongs to, per the provider."""

    email: str
    provider_account_id: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class ReplyMessage:
    """An inbound reply detected in a connected mailbox (read scope)."""

    from_email: str
    to_email: str | None
    subject: str | None
    received_at: datetime
    provider_message_id: str
    in_reply_to: str | None = None


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider_name: str
    model: str
    #: Populated when the call requested a JSON schema.
    parsed: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# Provider protocols
# --------------------------------------------------------------------------


class ShipmentsProvider(Protocol):
    """Trade statistics and, where available, transaction-level shipments."""

    name: str

    def trade_flows(
        self, hs_code: str, importer_iso2: str, years: int = 3
    ) -> list[ProviderRecord[TradeFlow]]: ...

    def top_exporters(
        self, hs_code: str, importer_iso2: str, limit: int = 10
    ) -> list[ProviderRecord[ExporterShare]]: ...

    def importer_shipments(
        self, hs_code: str, importer_iso2: str, limit: int = 100
    ) -> list[ProviderRecord[ShipmentRecord]]: ...


class EnrichmentProvider(Protocol):
    """Firmographic and decision-maker enrichment (Coresignal-shaped)."""

    name: str

    def enrich_company(
        self, name: str, country_iso2: str, domain: str | None = None
    ) -> ProviderRecord[CompanyFirmographics] | None: ...


class MapsProvider(Protocol):
    """Long-tail discovery in closed-customs-data markets (EU, GCC, Japan)."""

    name: str

    def search_importers(
        self, query: str, country_iso2: str, limit: int = 20
    ) -> list[ProviderRecord[MapsPlace]]: ...


class EmailFinderProvider(Protocol):
    name: str

    def find_contacts(
        self, company_name: str, domain: str | None, country_iso2: str
    ) -> list[ProviderRecord[FoundContact]]: ...


class EmailVerifier(Protocol):
    name: str

    def verify(self, email: str) -> VerificationResult: ...


class SendingProvider(Protocol):
    """Cold-email infrastructure. Never a transactional ESP."""

    name: str

    def send(self, message: OutboundEmail) -> SendResult: ...

    def register_webhook_events(self) -> None: ...


class MailboxProvider(Protocol):
    """A factory's own connected mailbox, sending on its behalf via OAuth.

    Unlike ``SendingProvider`` (one platform-wide cold-email vendor), a
    ``MailboxProvider`` acts per connected account: it drives the OAuth
    authorization-code flow, verifies the mailbox, sends through the account's
    API (Gmail / Microsoft Graph), and polls it for replies. Every send/verify/
    poll call is passed the account's decrypted ``MailboxCredentials`` — the
    provider itself is stateless and never touches the database.
    """

    name: str
    provider_type: str  # "gmail" | "microsoft" | "mock"

    #: Space-separated OAuth scopes requested — kept as narrow as possible
    #: (send + read for reply detection, nothing more).
    scopes: str

    def authorization_url(
        self, *, state: str, redirect_uri: str, login_hint: str | None = None
    ) -> str:
        """Build the provider consent URL the browser is redirected to."""
        ...

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokens:
        """Exchange an authorization code for access + refresh tokens."""
        ...

    def refresh(self, *, refresh_token: str) -> OAuthTokens:
        """Renew an access token. Raises ``TokenRefreshError`` if revoked."""
        ...

    def verify_mailbox(self, creds: MailboxCredentials) -> MailboxIdentity:
        """Confirm the token works and return the real mailbox identity."""
        ...

    def send(self, creds: MailboxCredentials, message: OutboundEmail) -> SendResult:
        """Send one message on behalf of the connected account."""
        ...

    def fetch_replies(self, creds: MailboxCredentials, since: datetime) -> list[ReplyMessage]:
        """Return replies received since ``since`` (read scope)."""
        ...


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse: ...

    def complete_with_image(
        self,
        *,
        system: str,
        prompt: str,
        image_bytes: bytes | None,
        media_type: str = "image/jpeg",
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse: ...


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...

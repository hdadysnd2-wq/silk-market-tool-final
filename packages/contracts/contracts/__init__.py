"""Silk platform-wide data contract (unified provenance envelope).

Locked architecture decision #4: Repo A's ``DataPoint`` and Repo B's
``ProviderRecord`` converge on ONE envelope that travels with every number in
the system, all the way to the database:

    {value, source, provider, confidence, fetched_at, data_year, note}

Guarantee I1 — *never fabricate data*: on any failure the envelope carries
``value=None`` and ``confidence=0.0`` with a human-readable ``note`` explaining
the gap. A missing number is always representable and always explains itself.

Adoption status
---------------
This package DEFINES the unified contract and the adapters that map each side's
existing model onto it. Both sides now have a live bridge into it — the engine
via ``from_datapoint`` (``services.engine``) and the platform via
``ProviderRecord.to_contract`` (``providers.base`` → ``from_provider_record``).
Column-level persistence of the full envelope is migrated strangler-style, so DB
rows still carry provenance as discrete columns where the envelope has not landed
yet; no big-bang rename.

Field mapping
-------------
    unified            DataPoint (Repo A)        ProviderRecord[T] (Repo B)
    -------            ------------------        --------------------------
    value              value                     data
    source             source                    source (SourceType)
    provider           (n/a — folded into note)  provider_name
    confidence         confidence                confidence
    fetched_at         retrieved_at (ISO date)   fetched_at (datetime)
    data_year          data_year                 (n/a)
    note               note                      (n/a)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")

__all__ = ["DataContract", "missing", "from_datapoint", "from_provider_record"]


@dataclass(frozen=True)
class DataContract(Generic[T]):
    """A value plus its full provenance — the one envelope for every number.

    ``value is None`` together with ``confidence == 0.0`` is the canonical
    "no data" state (I1). Consumers must render the ``note`` rather than
    substituting a placeholder number.
    """

    value: T | None
    source: str
    provider: str
    confidence: float
    fetched_at: str | None = None  # ISO-8601 string (date or datetime)
    data_year: int | None = None
    note: str = ""
    # Optional structural distinction carried by Repo A's engine:
    # "fetch_failed" (rate-limit/network — retryable) vs "no_record"
    # (successful response, genuinely empty). "" = unspecified.
    status: str = ""
    # When several sources jointly support one value, their atomic identifiers
    # are listed here explicitly (never merged into ``source``).
    sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_missing(self) -> bool:
        return self.value is None or self.confidence <= 0.0

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable view (assumes ``value`` is itself JSON-safe).

        Used at process/queue boundaries (Celery task returns, API responses)
        where the frozen dataclass must cross as plain JSON while keeping every
        provenance field — the envelope never gets stripped to a bare number.
        """
        return {
            "value": self.value,
            "source": self.source,
            "provider": self.provider,
            "confidence": self.confidence,
            "fetched_at": self.fetched_at,
            "data_year": self.data_year,
            "note": self.note,
            "status": self.status,
            "sources": list(self.sources),
            "is_missing": self.is_missing,
        }


def missing(source: str, provider: str, note: str, *, status: str = "") -> DataContract[Any]:
    """Construct the canonical 'no data' envelope (I1).

    Every failed fetch must return one of these — never a fabricated value.
    """
    return DataContract(
        value=None,
        source=source,
        provider=provider,
        confidence=0.0,
        note=note,
        status=status or "fetch_failed",
    )


def from_datapoint(dp: Any, *, provider: str = "") -> DataContract[Any]:
    """Adapt a Repo A ``DataPoint`` to the unified contract.

    Kept dependency-free (duck-typed) so this package imports neither side.
    ``provider`` is supplied by the caller because Repo A folded it into the
    ``source``/``note`` text rather than a dedicated field.
    """
    return DataContract(
        value=getattr(dp, "value", None),
        source=getattr(dp, "source", ""),
        provider=provider or getattr(dp, "source", ""),
        confidence=float(getattr(dp, "confidence", 0.0) or 0.0),
        fetched_at=getattr(dp, "retrieved_at", "") or None,
        data_year=getattr(dp, "data_year", None),
        note=getattr(dp, "note", "") or "",
        status=getattr(dp, "status", "") or "",
        # Repo A's DataPoint names this field ``source_ids`` (not ``sources``);
        # reading the wrong name silently dropped every composite attribution.
        sources=tuple(getattr(dp, "source_ids", None) or getattr(dp, "sources", ()) or ()),
    )


def from_provider_record(rec: Any) -> DataContract[Any]:
    """Adapt a Repo B ``ProviderRecord[T]`` to the unified contract."""
    fetched = getattr(rec, "fetched_at", None)
    src = getattr(rec, "source", "")
    # A ``SourceType`` enum carries a clean string in ``.value`` ("comtrade"); a
    # plain string passes through. Never emit "SourceType.COMTRADE".
    source = getattr(src, "value", None) or str(src)
    data = getattr(rec, "data", None)
    return DataContract(
        value=data,
        source=source,
        provider=getattr(rec, "provider_name", ""),
        # No payload ⇒ a missing envelope (I1): value None with zero confidence.
        confidence=float(getattr(rec, "confidence", 0.0) or 0.0) if data is not None else 0.0,
        fetched_at=fetched.isoformat() if hasattr(fetched, "isoformat") else fetched,
    )

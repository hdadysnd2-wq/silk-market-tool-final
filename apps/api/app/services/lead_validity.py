"""Lead validity window (compliance rule 6 / I8).

A discovered buyer's data is valid for 90 days. Rule 6: lead data carries a
90-day validity stamp and **stale data is shown with an explicit warning** — never
silently presented as current. Validity is derived from ``Buyer.freshness_at``
(when the record was last refreshed from its source) at read time, so it needs no
stored flag and is always accurate to "now". Unknown freshness is treated as
stale — the conservative, honest default (never assume a lead is fresh).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models import utcnow

#: A lead is considered current for this many days after it was last refreshed.
LEAD_VALIDITY_DAYS = 90


def valid_until(freshness_at: datetime | None) -> datetime | None:
    """The instant the lead's data stops being considered current, or None."""
    if freshness_at is None:
        return None
    return freshness_at + timedelta(days=LEAD_VALIDITY_DAYS)


def is_stale(freshness_at: datetime | None) -> bool:
    """Whether the lead is past its validity window (unknown freshness ⇒ stale)."""
    until = valid_until(freshness_at)
    if until is None:
        return True
    return utcnow() > until

"""Analysis runs and their engine-produced HS classifications (provenance-first).

Phase 1 persistence: an analysis run through the Celery worker persists to
Postgres with the full provenance envelope on every number (decision #4 / I1).
HS proposals are stored *unconfirmed* — the human-confirmation gate (I2) is never
bypassed; a proposal is not a committed customs declaration.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Analysis(UUIDMixin, TimestampMixin, Base):
    """One analysis run for a product — the spine record later steps hang off."""

    __tablename__ = "analyses"

    #: The product analysed. SET NULL (not CASCADE) so an analysis record — and
    #: its audit value — survives a product deletion.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        index=True,
    )
    #: Snapshot of the name that was analysed (survives product edits/deletes).
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="pending", nullable=False
    )  # pending | classified | failed
    #: Whether this run activated the paid /deepen scope (I5). Recorded for audit.
    deepen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class HSClassification(UUIDMixin, TimestampMixin, Base):
    """An engine HS6 proposal for an analysis, with its full provenance envelope.

    One row per ranked candidate. A no-match candidate keeps ``proposed_code=None``
    with ``confidence=0.0`` and a note (I1 — never a fabricated code).
    ``is_confirmed`` stays False until a human confirms (I2).
    """

    __tablename__ = "hs_classifications"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = best
    proposed_code: Mapped[str | None] = mapped_column(String(6))
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0, nullable=False)
    # Unified provenance envelope (decision #4 / I1).
    source: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    data_year: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text(), default="", nullable=False)
    # Human-confirmation gate (I2): a proposal is never auto-committed.
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

"""Analysis runs and their engine-produced HS classifications (provenance-first).

Phase 1 persistence: an analysis run through the Celery worker persists to
Postgres with the full provenance envelope on every number (decision #4 / I1).
HS proposals are stored *unconfirmed* — the human-confirmation gate (I2) is never
bypassed; a proposal is not a committed customs declaration.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
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
    )  # pending | classified | ranked | enriched | deepened | failed
    #: Human-readable reason a pipeline stage failed (set with the terminal
    #: ``failed`` status so the operator/UI sees why instead of a silent stall).
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    #: Whether this run activated the paid /deepen scope (I5). Recorded for audit.
    deepen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Total markets screened worldwide in Stage 1 (funnel transparency): lets the
    #: report show "screened N → shortlisted M → top 5" with the real world count,
    #: not the shortlist length. None for runs predating this column.
    total_screened: Mapped[int | None] = mapped_column(Integer)
    #: How many markets the Stage-1 top-20% cut kept for Stage 2 (J1 funnel
    #: transparency: "screened N → shortlisted M → top 5"). None for older runs.
    shortlisted: Mapped[int | None] = mapped_column(Integer)


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


class CountryRanking(UUIDMixin, TimestampMixin, Base):
    """A world-funnel country result for an analysis (the "world screened → top 5").

    Persists the Stage-1 screen output (``services.world_funnel``) bound to an
    analysis: the ranked importer, its screened score, and the transit-port /
    mirror / no-data provenance tags (I9 / I1). ``rank`` 1..5 is the shortlist the
    report surfaces as the top-5 export markets; ``stage`` records which funnel
    stage produced the row (1 = local screen; Stage 2/3 enrichment lands later).
    """

    __tablename__ = "country_rankings"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = best fit
    importer_iso3: Mapped[str] = mapped_column(String(3), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    #: Screened volume (None when no data — I1) and multi-year trend.
    import_usd: Mapped[float | None] = mapped_column(Numeric(18, 2))
    yoy_growth: Mapped[float | None] = mapped_column(Numeric(8, 4))
    cagr_3y: Mapped[float | None] = mapped_column(Numeric(8, 4))
    #: Score after the transit-port penalty (I9) — the value that set the rank.
    screen_score: Mapped[float] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    is_transit_hub: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_mirror: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Visible provenance tags ("transit hub — …", "mirror data", "no data").
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    #: Funnel stage that produced this row (1 = local screen; 2 = budgeted
    #: live enrichment of the shortlist).
    stage: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="world_trade", nullable=False)
    #: Stage-2 score after budgeted enrichment re-ranking (None until Stage 2 runs).
    stage2_score: Mapped[float | None] = mapped_column(Numeric(20, 4))
    #: Stage-2 enrichment signals + provenance ({applied_tariff_pct,
    #: ppp_gni_per_capita, source, note}). None until Stage 2 runs; a failed
    #: signal is a declared gap inside it (I1), never a fabricated number.
    enrichment: Mapped[dict | None] = mapped_column(JSONB)
    #: Stage-3 per-market deep-dive built from the engine's FREE offline layers
    #: ({competitors, requirements, threads}). None until Stage 3 runs; a finalist
    #: with no alpha-2 mapping is a declared gap inside it (I1), never fabricated.
    deepdive: Mapped[dict | None] = mapped_column(JSONB)

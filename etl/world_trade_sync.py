"""Bulk refresh of the ``world_trade`` table — Stage 1 of the world funnel.

Screens every importer in the world for a given HS6 from a *precomputed* table
so Stage 1 costs zero live API calls. This job precomputes that table from UN
Comtrade bulk endpoints (via ``comtradeapicall``), computing YoY growth and the
3-year CAGR, and applying the transit-port guard (invariant I9): re-export hubs
(AE, NL, SG, HK, BE, …) have their import volumes inflated by transshipment, so
their rows are tagged ``is_transit_hub`` and carry a visible penalty rather than
silently topping the ranking. Mirror-derived rows are tagged ``is_mirror``.

pandas + comtradeapicall live HERE ONLY (I7). They are imported lazily inside
``run()`` so this module stays importable without them and the repo-wide
no-pandas guard is satisfied everywhere else.

Phase 0: documented skeleton. The ``world_trade`` migration, the Stage-1 query
and the transit-hub fixture test land in Phase 2; first live sync in Phase 3.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

log = logging.getLogger(__name__)

# Re-export hubs whose import volumes are inflated by re-export / transshipment.
# Kept in sync with the ranking guard (invariant I9).
TRANSIT_HUBS: frozenset[str] = frozenset({"ARE", "NLD", "SGP", "HKG", "BEL"})

# Target table columns (materialised by the Phase 2 Alembic migration):
#   hs6, importer_iso3, year, import_usd, import_qty, yoy_growth, cagr_3y,
#   is_mirror, is_transit_hub, source, fetched_at
WORLD_TRADE_COLUMNS: tuple[str, ...] = (
    "hs6",
    "importer_iso3",
    "year",
    "import_usd",
    "import_qty",
    "yoy_growth",
    "cagr_3y",
    "is_mirror",
    "is_transit_hub",
    "source",
    "fetched_at",
)


# ---------------------------------------------------------------------------
# Pure transform helpers — no pandas, no network. These turn raw yearly import
# series into ``world_trade`` rows (the Stage-1 screening table): computing
# year-over-year growth and the 3-year CAGR, and tagging transit hubs (I9). The
# bulk Comtrade DOWNLOAD (pandas + comtradeapicall) stays in ``run()`` and is the
# Phase-3 live piece; these helpers are hermetically testable today.
# ---------------------------------------------------------------------------


def is_transit_hub(importer_iso3: str) -> bool:
    """Whether an importer is a re-export hub whose imports include re-exports (I9)."""
    return (importer_iso3 or "").upper() in TRANSIT_HUBS


def compute_yoy(series: dict[int, float | None]) -> float | None:
    """Year-over-year growth as a fraction from the two most recent years.

    ``None`` when there are fewer than two usable years or the base is zero — a
    gap is declared, never fabricated (I1).
    """
    years = sorted(y for y, v in series.items() if v is not None)
    if len(years) < 2:
        return None
    latest, prev = series[years[-1]], series[years[-2]]
    if not prev:  # zero or falsy base → undefined growth
        return None
    return (float(latest) - float(prev)) / float(prev)


def compute_cagr_3y(series: dict[int, float | None]) -> float | None:
    """Compound annual growth rate over the last ~3 years, as a fraction.

    Uses the most recent year and the year ~3 back (or the earliest available
    spanning ≥2 years). ``None`` when insufficient/degenerate (I1).
    """
    years = sorted(y for y, v in series.items() if v is not None and v > 0)
    if len(years) < 2:
        return None
    end_year = years[-1]
    start_year = max((y for y in years if y <= end_year - 3), default=years[0])
    span = end_year - start_year
    if span <= 0:
        return None
    ratio = float(series[end_year]) / float(series[start_year])
    return ratio ** (1.0 / span) - 1.0


def build_rows(
    hs6: str,
    imports_usd: dict[str, dict[int, float | None]],
    *,
    source: str = "UN Comtrade",
    fetched_at: str | None = None,
    mirror_importers: set[str] | None = None,
    qty: dict[str, dict[int, float | None]] | None = None,
) -> list[dict]:
    """Turn per-importer yearly import series into latest-year ``world_trade`` rows.

    ``imports_usd`` maps ISO3 → {year: import_usd}. One row is emitted per importer
    for its latest year, carrying computed ``yoy_growth``/``cagr_3y`` and the
    ``is_transit_hub`` (I9) / ``is_mirror`` provenance flags. Rows are ready to
    upsert into ``world_trade`` (keys match ``WORLD_TRADE_COLUMNS``).
    """
    mirror = {m.upper() for m in (mirror_importers or set())}
    rows: list[dict] = []
    for iso3, series in imports_usd.items():
        usable_years = [y for y, v in series.items() if v is not None]
        if not usable_years:
            continue
        year = max(usable_years)
        qty_series = (qty or {}).get(iso3, {})
        rows.append(
            {
                "hs6": hs6,
                "importer_iso3": iso3.upper(),
                "year": year,
                "import_usd": series[year],
                "import_qty": qty_series.get(year),
                "yoy_growth": compute_yoy(series),
                "cagr_3y": compute_cagr_3y(series),
                "is_transit_hub": is_transit_hub(iso3),
                "is_mirror": iso3.upper() in mirror,
                "source": source,
                "fetched_at": fetched_at,
            }
        )
    return rows


#: Type of the two injectable seams (real defaults do the live download / DB
#: upsert; tests inject fakes so the orchestration is hermetically verifiable).
Fetcher = Callable[[str, Sequence[int]], "tuple[dict, dict, set[str]]"]
Writer = Callable[[list[dict]], int]


def _default_years(n: int = 3) -> list[int]:
    """The last ``n`` likely-complete data years (previous calendar year back)."""
    latest = datetime.now(UTC).year - 1
    return list(range(latest - n + 1, latest + 1))


#: Column-name aliases tolerated in the Comtrade bulk response. The live schema
#: has never been confirmed against the paid API (see ``_fetch_world_imports``),
#: so each field resolves against a small set of documented/observed spellings,
#: case-insensitively. A genuinely unrecognized schema becomes a LOUD declared
#: gap (I1) that names the columns actually received — never a silent all-drop
#: that would read as "the world doesn't import this".
_ISO_COLS = ("reporterISO", "reporterCodeIsoAlpha3", "ReporterISO", "reporteriso")
_VALUE_COLS = ("primaryValue", "PrimaryValue", "TradeValue", "cifvalue", "tradeValue")
_QTY_COLS = ("qty", "Qty", "primaryQty", "primaryqty")


def resolve_columns(
    columns: Sequence[str],
) -> tuple[str | None, str | None, str | None]:
    """Map (importer-ISO, import-value, quantity) onto the ACTUAL column names in
    a Comtrade response, case-insensitively, via :data:`_ISO_COLS` etc.

    Returns ``(iso_col, value_col, qty_col)``; any field whose alias is absent is
    ``None``. Pure (no pandas) so the schema tolerance is hermetically testable —
    the reason it exists is the one-time live-verification risk: an unexpected
    spelling must be diagnosable from a log, not swallowed as empty coverage.
    """
    lower = {str(c).lower(): c for c in columns}

    def pick(aliases: tuple[str, ...]) -> str | None:
        for alias in aliases:
            hit = lower.get(alias.lower())
            if hit is not None:
                return hit
        return None

    return pick(_ISO_COLS), pick(_VALUE_COLS), pick(_QTY_COLS)


def run(
    hs6: str | None = None,
    years: Sequence[int] | None = None,
    *,
    fetcher: Fetcher | None = None,
    writer: Writer | None = None,
) -> int:
    """Refresh ``world_trade`` for one HS6 (live bulk sync).

    Orchestrates three steps: **fetch** per-importer yearly import series from UN
    Comtrade bulk endpoints, **transform** them into rows via :func:`build_rows`
    (YoY/CAGR + the I9 transit-hub / mirror flags), and **upsert** them into
    ``world_trade``. Returns the number of rows written.

    ``fetcher`` and ``writer`` are injectable seams: the real defaults lazy-import
    pandas + comtradeapicall (the live download, I7 — here only) and SQLAlchemy
    (the DB upsert), so this module still imports with neither installed and the
    orchestration is hermetically testable with fakes. The heavy pieces are the
    live-verification step; the transform is proven today.
    """
    if not hs6:
        raise ValueError(
            "world_trade_sync.run() requires an --hs6 code (full-scope batch is TODO)"
        )
    hs6 = hs6.strip()
    resolved_years = list(years) if years else _default_years()
    fetch = fetcher or _fetch_world_imports
    write = writer or _upsert_world_trade

    imports_usd, qty, mirror = fetch(hs6, resolved_years)
    rows = build_rows(
        hs6,
        imports_usd,
        source="UN Comtrade",
        fetched_at=datetime.now(UTC).isoformat(),
        mirror_importers=mirror,
        qty=qty,
    )
    return write(rows)


def _fetch_world_imports(
    hs6: str, years: Sequence[int]
) -> tuple[
    dict[str, dict[int, float | None]], dict[str, dict[int, float | None]], set[str]
]:
    """Live bulk download: world imports of ``hs6`` by every reporter, per year.

    Returns ``(imports_usd, imports_qty, mirror_importers)`` where each map is
    ISO3 → {year: value}. Uses UN Comtrade bulk data via ``comtradeapicall`` and
    pandas (I7 — permitted HERE ONLY; imported lazily so the module loads without
    them). A year whose fetch fails contributes no value (a declared gap, I1) —
    never a fabricated figure.

    Wiring: the product triggers this via ``app.workers.tasks.sync_world_trade``
    (fail-closed on a real ``COMTRADE_API_KEY``) — on demand when an analysis hits
    an HS6 with no coverage, and on a daily scheduled sweep for confirmed HS6
    codes. The world funnel now fails loudly on missing coverage instead of
    returning a silent empty shortlist.

    ⚠️ One-time operator live-verification (cannot be done offline): the exact
    ``comtradeapicall`` entry point (``getFinalData``) and the returned column
    names (``reporterISO`` / ``primaryValue`` / ``qty``) must be confirmed against
    the live API on the first real run with the Railway ``COMTRADE_API_KEY`` — the
    fail-closed guard keeps every offline/CI path from ever calling it. Kept
    deliberately small and defensive.
    """
    import contextlib
    import io
    import socket

    import comtradeapicall  # (lazy, etl-only — I7)
    import pandas as pd  # (lazy, etl-only — I7)

    subscription_key = os.environ.get("COMTRADE_API_KEY", "")
    # comtradeapicall exposes no timeout parameter, so its socket reads are
    # unbounded — inside a Celery worker that means hanging until the 660s
    # hard-limit SIGKILL, which bypasses failure marking and redelivers the
    # task forever (symptom B #5). Bound every socket in this process for the
    # duration of the fetch; restore afterwards.
    _prev_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(float(os.environ.get("COMTRADE_SOCKET_TIMEOUT", "120")))
    imports_usd: dict[str, dict[int, float | None]] = {}
    imports_qty: dict[str, dict[int, float | None]] = {}

    def _clean(value: object) -> float | None:
        # Comtrade returns NaN for absent figures; keep it a declared gap (I1).
        return None if value is None or pd.isna(value) else _as_float(value)

    try:
        for year in years:
            # comtradeapicall SWALLOWS request failures: it print()s
            # "Request error: …" and returns an empty DataFrame instead of
            # raising (PreviewGet.getPreviewData, shared by getFinalData) — so
            # a network/auth failure is indistinguishable from a genuinely
            # empty dataset and our except-branch never fires. Capture the
            # library's stdout and surface anything it printed as a structured
            # WARNING (live incident 2026-08-08: `world_trade_synced rows=0`
            # with no error line anywhere).
            _lib_out = io.StringIO()
            try:
                # Imports (flowCode="M"), all reporters, partner=World (0), HS6.
                # Param set mirrors the repo's PROVEN Comtrade client
                # (silk_data_layer._comtrade_call): reporter omitted ⇒ every
                # reporter (the library drops None params), partner=0 ⇒ World,
                # and NO customs/mot/partner2 filters — the proven path never
                # sends them, and any of them over-filtering was a prime
                # suspect for the all-years-empty live result.
                with contextlib.redirect_stdout(_lib_out):
                    df = comtradeapicall.getFinalData(
                        subscription_key,
                        typeCode="C",
                        freqCode="A",
                        clCode="HS",
                        period=str(year),
                        reporterCode=None,  # dropped by the library ⇒ every reporter
                        cmdCode=hs6,
                        flowCode="M",
                        partnerCode="0",  # World
                        partner2Code=None,
                        customsCode=None,
                        motCode=None,
                    )
            except Exception as exc:  # noqa: BLE001 — a failed year is a declared gap (I1)
                log.warning(
                    "comtrade_bulk_year_failed hs6=%s year=%s error=%s", hs6, year, exc
                )
                continue
            _lib_msg = _lib_out.getvalue().strip()
            if _lib_msg:
                log.warning(
                    "comtrade_call_output hs6=%s year=%s output=%s",
                    hs6, year, _lib_msg[:500],
                )
            if df is None or getattr(df, "empty", True):
                # Empty-but-successful is a DECLARED gap, never silence — before
                # this line the incident signature was `rows=0` with no per-year
                # trace at all.
                log.warning("comtrade_empty_result hs6=%s year=%s", hs6, year)
                continue
            # Resolve the ISO / value / qty columns against the schema actually
            # returned (tolerant of spelling drift). If the mandatory two are
            # absent, this year is a DECLARED gap whose log NAMES the columns
            # received — the exact signal the one-time live-verification needs,
            # instead of silently dropping every row.
            iso_col, val_col, qty_col = resolve_columns(list(df.columns))
            if iso_col is None or val_col is None:
                log.error(
                    "comtrade_schema_unrecognized hs6=%s year=%s columns=%s",
                    hs6,
                    year,
                    list(df.columns),
                )
                continue
            for _, row in df.iterrows():
                iso3 = str(row.get(iso_col) or "").upper()
                if not iso3 or len(iso3) != 3:
                    continue
                imports_usd.setdefault(iso3, {})[year] = _clean(row.get(val_col))
                imports_qty.setdefault(iso3, {})[year] = (
                    _clean(row.get(qty_col)) if qty_col else None
                )
    finally:
        socket.setdefaulttimeout(_prev_timeout)

    # Mirror-data derivation (reconstructing a non-reporter's imports from partner
    # exports) is a future enhancement; none derived here.
    return imports_usd, imports_qty, set()


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _upsert_world_trade(rows: list[dict]) -> int:
    """Upsert ``world_trade`` rows, keyed on (hs6, importer_iso3, year).

    Uses SQLAlchemy Core against ``DATABASE_URL`` (imported lazily — not an
    apps/api dependency here). ``id``/``created_at``/``updated_at`` are ORM-side
    defaults on the model, so this Core path supplies them explicitly. Existing
    rows are updated in place (idempotent monthly/quarterly refresh).
    """
    if not rows:
        return 0

    import uuid

    from sqlalchemy import (
        Boolean,
        Column,
        DateTime,
        Integer,
        MetaData,
        Numeric,
        String,
        Table,
        create_engine,
    )
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set to upsert world_trade")

    metadata = MetaData()
    world_trade = Table(
        "world_trade",
        metadata,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("hs6", String(6), nullable=False),
        Column("importer_iso3", String(3), nullable=False),
        Column("year", Integer, nullable=False),
        Column("import_usd", Numeric(18, 2)),
        Column("import_qty", Numeric(18, 2)),
        Column("yoy_growth", Numeric(8, 4)),
        Column("cagr_3y", Numeric(8, 4)),
        Column("is_transit_hub", Boolean, nullable=False),
        Column("is_mirror", Boolean, nullable=False),
        Column("source", String(64), nullable=False),
        Column("fetched_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )

    now = datetime.now(UTC)
    payload = [
        {**row, "id": uuid.uuid4(), "created_at": now, "updated_at": now}
        for row in rows
    ]

    engine = create_engine(database_url)
    written = 0
    with engine.begin() as conn:
        for record in payload:
            stmt = pg_insert(world_trade).values(**record)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_world_trade_hs6_importer_year",
                set_={
                    "import_usd": stmt.excluded.import_usd,
                    "import_qty": stmt.excluded.import_qty,
                    "yoy_growth": stmt.excluded.yoy_growth,
                    "cagr_3y": stmt.excluded.cagr_3y,
                    "is_transit_hub": stmt.excluded.is_transit_hub,
                    "is_mirror": stmt.excluded.is_mirror,
                    "source": stmt.excluded.source,
                    "fetched_at": stmt.excluded.fetched_at,
                    "updated_at": now,
                },
            )
            conn.execute(stmt)
            written += 1
    engine.dispose()
    return written


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Refresh the world_trade table (Stage 1).")
    p.add_argument("--hs6", help="HS6 code to refresh; omit for the full scope.")
    p.add_argument("--years", nargs="*", type=int, help="Data years to pull.")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    return run(hs6=args.hs6, years=args.years)


if __name__ == "__main__":
    raise SystemExit(main())

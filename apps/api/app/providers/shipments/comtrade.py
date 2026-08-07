"""UN Comtrade adapter — free aggregate trade statistics.

Offline (``COMTRADE_OFFLINE``, the CI/demo default) the adapter reads committed
fixtures, which keeps CI and demos deterministic on zero keys. *Live*, it does
not talk to Comtrade directly: every live call routes through the engine's
hardened data layer (``silk_data_layer.comtrade_trade``, locked decision #5),
which carries provenance, per-host throttling, a circuit breaker, per-source
cache TTL, and mirror-data fallback — none of which this thin adapter has. When
every year's live fetch fails, it degrades to the committed fixtures rather than
fabricate a figure (I1).

Comtrade publishes country-level aggregates, not company-level shipments, so
``importer_shipments`` returns nothing here; transaction-level data comes from
the bulk customs adapter.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.providers.base import (
    ExporterShare,
    ProviderRecord,
    ShipmentRecord,
    SourceType,
    TradeFlow,
)
from app.providers.countries import country_name, iso2_to_m49, m49_to_iso2

log = get_logger(__name__)

FIXTURES = Path(__file__).resolve().parents[2] / "seeds" / "fixtures" / "comtrade"


class ComtradeProvider:
    """Aggregate market sizing and competitor shares."""

    name = "comtrade"

    def __init__(
        self,
        api_key: str = "",
        offline: bool = True,
        cache_dir: Path | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self.offline = offline
        self._cache_dir = cache_dir or FIXTURES
        self._timeout = timeout

    # -- protocol ----------------------------------------------------------

    def trade_flows(
        self, hs_code: str, importer_iso2: str, years: int = 3
    ) -> list[ProviderRecord[TradeFlow]]:
        payload = self._fetch(hs_code, importer_iso2)
        current_year = datetime.now(UTC).year
        wanted = {current_year - offset for offset in range(1, years + 1)}

        by_year: dict[int, float] = {}
        for row in payload.get("data", []):
            year = int(row.get("refYear") or row.get("period") or 0)
            if year not in wanted and wanted:
                continue
            by_year[year] = by_year.get(year, 0.0) + float(row.get("primaryValue") or 0.0)

        prov_name, prov_conf = self._provenance(payload)
        records = []
        for year, value in sorted(by_year.items()):
            records.append(
                ProviderRecord(
                    data=TradeFlow(
                        hs_code=hs_code,
                        importer_iso2=importer_iso2,
                        year=year,
                        value_usd=value,
                    ),
                    source=SourceType.COMTRADE,
                    provider_name=prov_name,
                    confidence=prov_conf,
                    fetched_at=self._fetched_at(payload),
                )
            )
        return records

    def top_exporters(
        self, hs_code: str, importer_iso2: str, limit: int = 10
    ) -> list[ProviderRecord[ExporterShare]]:
        payload = self._fetch(hs_code, importer_iso2)
        rows = payload.get("data", [])
        if not rows:
            return []

        latest_year = max(int(r.get("refYear") or r.get("period") or 0) for r in rows)
        totals: dict[str, float] = {}
        for row in rows:
            if int(row.get("refYear") or row.get("period") or 0) != latest_year:
                continue
            raw_partner = str(row.get("partnerCode") or "")
            # Exclude the "World" aggregate row (M49 code 0) BEFORE converting to
            # ISO2 — the aggregate would otherwise be summed into grand_total and
            # inflate it, halving every real exporter's share_pct.
            if raw_partner.strip().lstrip("0") == "":
                continue
            partner = m49_to_iso2(raw_partner)
            if not partner:
                continue
            totals[partner] = totals.get(partner, 0.0) + float(row.get("primaryValue") or 0.0)

        grand_total = sum(totals.values())
        if grand_total <= 0:
            return []

        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        fetched = self._fetched_at(payload)
        prov_name, prov_conf = self._provenance(payload)
        return [
            ProviderRecord(
                data=ExporterShare(
                    exporter_iso2=iso2,
                    exporter_name=country_name(iso2),
                    value_usd=value,
                    share_pct=round(100 * value / grand_total, 2),
                    year=latest_year,
                ),
                source=SourceType.COMTRADE,
                provider_name=prov_name,
                confidence=prov_conf,
                fetched_at=fetched,
            )
            for iso2, value in ranked
        ]

    def importer_shipments(
        self, hs_code: str, importer_iso2: str, limit: int = 100
    ) -> list[ProviderRecord[ShipmentRecord]]:
        # Comtrade is country-level only; company-level movements come from the
        # bulk customs adapter.
        return []

    # -- internals ---------------------------------------------------------

    def _cache_path(self, hs_code: str, importer_iso2: str) -> Path:
        return self._cache_dir / f"{importer_iso2.upper()}_{hs_code}.json"

    def _fetched_at(self, payload: dict[str, Any]) -> datetime:
        raw = payload.get("_fetched_at")
        if raw:
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                pass
        return datetime.now(UTC)

    def _provenance(self, payload: dict[str, Any]) -> tuple[str, float]:
        """(provider_name, confidence) reflecting the payload's ACTUAL origin.

        Offline fixtures and live-failure fallbacks must not present as genuine
        live UN Comtrade (audit C7): a fixture-served payload is stamped
        ``comtrade_fixture`` at a lowered confidence so the stored snapshot rows
        and the executive report show the substitution honestly (I1).
        """
        if payload.get("_provenance") == "live":
            return self.name, 0.9
        return "comtrade_fixture", 0.4

    def _fetch(self, hs_code: str, importer_iso2: str) -> dict[str, Any]:
        cache_path = self._cache_path(hs_code, importer_iso2)

        if self.offline:
            payload = self._read_cache(cache_path, hs_code, importer_iso2)
            payload["_provenance"] = "fixture"
            return payload

        payload = self._fetch_live(hs_code, importer_iso2)
        if payload is None:
            # Every year's fetch failed (rate limit / network / circuit open).
            # Degrade to committed fixtures — never fabricate a figure (I1).
            log.warning(
                "comtrade_fetch_failed_using_cache",
                hs_code=hs_code,
                importer=importer_iso2,
            )
            payload = self._read_cache(cache_path, hs_code, importer_iso2)
            payload["_provenance"] = "degraded_fixture"
            return payload
        payload["_provenance"] = "live"
        self._write_cache(cache_path, payload)
        return payload

    def _fetch_live(self, hs_code: str, importer_iso2: str) -> dict[str, Any] | None:
        """Live Comtrade via the engine's hardened data layer (locked decision #5).

        All *live* Comtrade calls go through ``silk_data_layer.comtrade_trade`` —
        it carries provenance, per-host throttling, a circuit breaker, per-source
        cache TTL, and mirror-data fallback; this adapter has none of those. One
        call per year (imports into the target market, every partner). Returns a
        ``{"data": [...]}`` payload in the shape the parsers expect, or ``None`` if
        *every* year's fetch failed (the caller then degrades to committed
        fixtures — a failed source is a declared gap, never a fabricated one, I1).
        """
        import silk_data_layer

        # Per-analysis call budget (locked decision #5): each year is one live
        # call. When the analysis budget is exhausted we stop and let the caller
        # degrade to cache/fixtures — a spent budget is a declared gap, never a
        # fabricated figure (I1). Unmetered (returns True) outside a budget scope.
        from app.services.api_budget import charge

        reporter_m49 = iso2_to_m49(importer_iso2)
        current_year = datetime.now(UTC).year
        records: list[dict[str, Any]] = []
        any_ok = False
        for offset in range(1, 4):
            year = current_year - offset
            if not charge(1, source="comtrade"):
                log.warning(
                    "comtrade_budget_exhausted",
                    hs_code=hs_code,
                    importer=importer_iso2,
                    year=year,
                )
                break
            # partner="all" omits partnerCode so Comtrade returns every partner;
            # None means the year's fetch failed (429/network) — distinct from an
            # empty-but-successful [] (the engine layer already logged the cause).
            rows = silk_data_layer.comtrade_trade(
                hs_code, reporter_m49, year, flow="M", partner="all"
            )
            if rows is None:
                continue
            any_ok = True
            records.extend(rows)
        if not any_ok:
            return None
        return {"data": records, "_fetched_at": datetime.now(UTC).isoformat()}

    def _read_cache(self, path: Path, hs_code: str, importer_iso2: str) -> dict[str, Any]:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        log.info("comtrade_no_fixture", hs_code=hs_code, importer=importer_iso2)
        return {"data": []}

    def _write_cache(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - cache is best effort
            log.warning("comtrade_cache_write_failed", error=str(exc))

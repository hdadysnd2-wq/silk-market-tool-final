"""UN Comtrade adapter — free aggregate trade statistics.

Comtrade needs no API key, so this is the one integration that talks to a real
external service by default. Responses are cached on disk and the adapter falls
back to committed fixtures when the network is unavailable or ``COMTRADE_OFFLINE``
is set, which keeps CI and demos deterministic.

Comtrade publishes country-level aggregates, not company-level shipments, so
``importer_shipments`` returns nothing here; transaction-level data comes from
the bulk customs adapter.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

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

COMTRADE_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
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
                    provider_name=self.name,
                    confidence=0.9,
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
                provider_name=self.name,
                confidence=0.9,
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

    def _fetch(self, hs_code: str, importer_iso2: str) -> dict[str, Any]:
        cache_path = self._cache_path(hs_code, importer_iso2)

        if self.offline:
            return self._read_cache(cache_path, hs_code, importer_iso2)

        try:
            params = {
                "reporterCode": iso2_to_m49(importer_iso2),
                "flowCode": "M",  # imports into the target market
                "cmdCode": hs_code,
                "period": ",".join(str(datetime.now(UTC).year - offset) for offset in range(1, 4)),
                "partnerCode": "",
                "includeDesc": "true",
            }
            headers = {"Ocp-Apim-Subscription-Key": self._api_key} if self._api_key else {}
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(COMTRADE_URL, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
            payload["_fetched_at"] = datetime.now(UTC).isoformat()
            self._write_cache(cache_path, payload)
            return payload
        except Exception as exc:  # network, rate limit, schema drift
            log.warning(
                "comtrade_fetch_failed_using_cache",
                hs_code=hs_code,
                importer=importer_iso2,
                error=str(exc),
            )
            return self._read_cache(cache_path, hs_code, importer_iso2)

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

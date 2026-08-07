"""Volza bill-of-lading adapter — READY, AWAITING SUBSCRIPTION.

The live vendor seam for company-level customs shipments (J4). With a
``VOLZA_API_KEY`` the registry selects this adapter and buyer discovery's
customs step runs on real bills of lading instead of the loudly-labeled
sample provider. Until the subscription exists the adapter is unproven
against the live API (same ⚠ verify-live class as the other paid adapters
in docs/PHASE3_ADAPTER_READINESS.md) — auth, request shape, and field
probing mirror the engine's ``silk_volza_agent`` (Bearer key, ``hsCode``/
``country`` params, plan-dependent response containers).

Contract discipline:

- Company names are read ONLY from the real response — a nameless row is
  dropped, never fabricated (I1).
- Any failure (network, auth, non-JSON, unexpected shape) degrades to an
  empty list with a logged warning — it never raises into a discovery run.
- Aggregates (trade flows / top exporters) are Comtrade's job
  (``get_comtrade_provider``); this adapter declares those gaps as ``[]``.
"""

from __future__ import annotations

from datetime import date

import httpx

from app.logging import get_logger
from app.providers.base import (
    ExporterShare,
    ProviderRecord,
    ShipmentRecord,
    SourceType,
    TradeFlow,
)
from app.providers.countries import iso2_to_iso3, iso3_to_iso2

log = get_logger(__name__)

#: Base URL for the Volza data API. The paid host/path can differ per
#: subscription plan, so it is configurable (``VOLZA_API_URL``) — the same
#: reason the engine's agent reads that env var.
DEFAULT_VOLZA_API_URL = "https://api.volza.com/v1"


class VolzaShipmentsProvider:
    """Company-level import shipments from Volza bills of lading (paid)."""

    name = "volza"

    def __init__(
        self,
        api_key: str,
        api_url: str = DEFAULT_VOLZA_API_URL,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        # A blank override (e.g. an empty VOLZA_API_URL in .env) falls back to
        # the default rather than producing a scheme-less URL.
        self._api_url = (api_url or DEFAULT_VOLZA_API_URL).rstrip("/")
        self._timeout = timeout

    def importer_shipments(
        self, hs_code: str, importer_iso2: str, limit: int = 100
    ) -> list[ProviderRecord[ShipmentRecord]]:
        dest_iso3 = iso2_to_iso3(importer_iso2)
        if not dest_iso3:
            log.warning("volza_no_iso3_mapping", market=importer_iso2)
            return []
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(
                    f"{self._api_url}/import/shipments",
                    # Key travels in the Authorization header, never in params.
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept": "application/json",
                    },
                    params={
                        "hsCode": hs_code,
                        "country": dest_iso3,
                        "limit": limit,
                    },
                )
                response.raise_for_status()
                rows = _rows(response.json())
        # Degrade on any failure (network, auth, non-JSON body, unexpected
        # shape) to an empty result rather than crashing the discovery run (I1).
        except Exception as exc:
            log.warning(
                "volza_shipments_failed",
                hs_code=hs_code,
                market=importer_iso2,
                error=str(exc),
            )
            return []

        records: list[ProviderRecord[ShipmentRecord]] = []
        for row in rows:
            shipment = _map_row(row, hs_code, importer_iso2)
            if shipment is None:
                continue  # nameless row — never fabricate an importer (I1)
            records.append(
                ProviderRecord(
                    data=shipment,
                    source=SourceType.CUSTOMS,
                    provider_name=self.name,
                    confidence=0.9,
                )
            )
            if len(records) >= limit:
                break
        return records

    def trade_flows(
        self, hs_code: str, importer_iso2: str, years: int = 3
    ) -> list[ProviderRecord[TradeFlow]]:
        # Aggregate flows come from Comtrade (get_comtrade_provider); Volza's
        # role here is company-level shipments only. Declared gap, not a guess.
        return []

    def top_exporters(
        self, hs_code: str, importer_iso2: str, limit: int = 10
    ) -> list[ProviderRecord[ExporterShare]]:
        # Same split as trade_flows: market aggregates are Comtrade's job.
        return []


# --------------------------------------------------------------------------
# Response mapping — Volza response shapes vary by plan, so every field is
# probed defensively (the engine's silk_volza_agent does the same).
# --------------------------------------------------------------------------


def _rows(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("results") or payload.get("shipments") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def _map_row(row: dict, hs_code: str, importer_iso2: str) -> ShipmentRecord | None:
    """One vendor row → one ``ShipmentRecord``; ``None`` when no importer name.

    Unparseable optional fields become ``None`` (declared gaps — the scorer
    already tolerates a dateless/valueless shipment), never invented values.
    """
    name = _text(row, "importerName", "importer", "consigneeName", "companyName", "name")
    if not name:
        return None
    return ShipmentRecord(
        consignee_name=name,
        hs_code=_text(row, "hsCode", "hs_code") or hs_code,
        origin_iso2=_origin_iso2(row) or "",
        dest_iso2=importer_iso2,
        shipment_date=_parse_date(_first(row, "shipmentDate", "date", "arrivalDate")),
        value_usd=_number(_first(row, "valueUsd", "valueUSD", "cifValueUsd", "value")),
        quantity=_number(_first(row, "quantity", "qty")),
        quantity_unit=_text(row, "quantityUnit", "unit") or None,
        shipper_name=_text(row, "exporterName", "exporter", "shipperName") or None,
        external_id=_text(row, "shipmentId", "recordId", "id") or None,
        consignee_city=_text(row, "importerCity", "city") or None,
    )


def _first(row: dict, *keys: str) -> object | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(row: dict, *keys: str) -> str:
    value = _first(row, *keys)
    return str(value).strip() if value is not None else ""


def _origin_iso2(row: dict) -> str | None:
    value = _first(row, "originCountryIso2", "originCountry", "countryOfOrigin", "origin")
    if value is None:
        return None
    text = str(value).strip().upper()
    if len(text) == 2:
        return text
    if len(text) == 3:
        return iso3_to_iso2(text)
    return None  # a country name we hold no code for — gap, not a guess


def _parse_date(value: object | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

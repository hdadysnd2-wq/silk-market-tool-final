"""J4 lock: the shipment-data vendor seam (Volza) + loud SAMPLE labeling.

The registry used to return ``MockShipmentsProvider`` UNCONDITIONALLY, so a
keyless production deploy silently minted fabricated importers as
``BuyerSource.customs`` rows. The slot now follows the C3 pattern
(``test_no_mock_data_in_prod.py``): key → live Volza adapter; keyless local
(or the explicit demo opt-in) → the sample provider whose every company name
is loudly prefixed "SAMPLE — "; keyless anywhere else → a declared gap.
"""

from __future__ import annotations

from datetime import date

import httpx

from app.config import Settings
from app.providers.base import SourceType
from app.providers.registry import get_shipments_provider
from app.providers.shipments.mock import SAMPLE_NAME_PREFIX
from app.providers.shipments.volza import VolzaShipmentsProvider


def _settings(**overrides) -> Settings:
    base = {
        "environment": "production",
        "secret_key": "x" * 40,
        "token_encryption_key": "t" * 44,
        # Satisfy the H7 safe-prod-networking validator (config.py) — these are
        # unrelated to the shipments slot but required for any prod Settings.
        "trusted_proxy_count": 1,
        "api_base_url": "https://api.silk.example",
    }
    base.update(overrides)
    return Settings(**base)


# -- registry selection ------------------------------------------------------


def test_keyless_prod_shipments_are_a_declared_gap():
    provider = get_shipments_provider(_settings())
    assert provider.name == "gated-shipments"
    assert provider.importer_shipments("392010", "AE") == []
    assert provider.trade_flows("392010", "AE") == []
    assert provider.top_exporters("392010", "AE") == []


def test_local_gets_the_sample_provider_with_loud_labels():
    provider = get_shipments_provider(_settings(environment="local"))
    assert provider.name == "customs_sample"
    records = provider.importer_shipments("392010", "IN", limit=50)
    assert records
    for rec in records:
        assert rec.data.consignee_name.startswith(SAMPLE_NAME_PREFIX)
        assert rec.provider_name == "customs_sample"


def test_explicit_demo_opt_in_unlocks_sample_outside_local():
    provider = get_shipments_provider(_settings(allow_mock_data=True))
    assert provider.name == "customs_sample"


def test_volza_key_selects_the_live_adapter():
    provider = get_shipments_provider(_settings(volza_api_key="k"))
    assert isinstance(provider, VolzaShipmentsProvider)
    assert provider.name == "volza"


# -- Volza adapter mapping / degradation ------------------------------------
# Same httpx.Client stand-in pattern as tests/test_provider_adapters.py.


class _Resp:
    def __init__(self, json_value=None, raises=False, status_error=False):
        self._json_value = json_value
        self._raises = raises
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error:
            raise httpx.HTTPStatusError(
                "401 Unauthorized",
                request=httpx.Request("GET", "https://api.volza.com/v1/import/shipments"),
                response=httpx.Response(401),
            )
        return None

    def json(self):
        if self._raises:
            raise ValueError("not JSON")
        return self._json_value


class _Client:
    last_kwargs: dict = {}

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, *args, **kwargs):
        _Client.last_kwargs = kwargs
        return self._resp


def _patch(monkeypatch, resp):
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _Client(resp))


_VOLZA_PAYLOAD = {
    "data": [
        {
            "importerName": "Gulf Star Trading LLC",
            "hsCode": "392010",
            "originCountry": "SAU",
            "shipmentDate": "2026-05-14",
            "valueUsd": "18500.5",
            "quantity": 9200,
            "quantityUnit": "KG",
            "exporterName": "Riyadh Polymers",
            "shipmentId": "VZ-1",
            "importerCity": "Dubai",
        },
        # Nameless row: dropped — an importer name is never fabricated (I1).
        {"shipmentDate": "2026-01-01", "valueUsd": 100},
        # Unparseable optional fields become declared gaps, not inventions.
        {"importerName": "Delta Foods FZE", "shipmentDate": "n/a", "valueUsd": "n/a"},
    ]
}


def test_volza_maps_the_vendor_response_to_protocol_records(monkeypatch):
    _patch(monkeypatch, _Resp(json_value=_VOLZA_PAYLOAD))
    records = VolzaShipmentsProvider("key").importer_shipments("392010", "AE")

    assert [r.data.consignee_name for r in records] == [
        "Gulf Star Trading LLC",
        "Delta Foods FZE",
    ]
    first = records[0]
    assert first.source is SourceType.CUSTOMS
    assert first.provider_name == "volza"
    data = first.data
    assert data.hs_code == "392010"
    assert data.origin_iso2 == "SA"  # vendor ISO3 mapped back to alpha-2
    assert data.dest_iso2 == "AE"
    assert data.shipment_date == date(2026, 5, 14)
    assert data.value_usd == 18500.5
    assert data.quantity == 9200.0
    assert data.quantity_unit == "KG"
    assert data.shipper_name == "Riyadh Polymers"
    assert data.external_id == "VZ-1"
    assert data.consignee_city == "Dubai"

    gappy = records[1].data
    assert gappy.shipment_date is None
    assert gappy.value_usd is None


def test_volza_authenticates_via_bearer_header_not_params(monkeypatch):
    _patch(monkeypatch, _Resp(json_value={"data": []}))
    VolzaShipmentsProvider("secret-key").importer_shipments("392010", "AE")
    kwargs = _Client.last_kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in str(kwargs["params"])
    # Volza is keyed by ISO3 on the destination market.
    assert kwargs["params"]["country"] == "ARE"


def test_volza_http_error_degrades_to_empty(monkeypatch):
    _patch(monkeypatch, _Resp(status_error=True))
    assert VolzaShipmentsProvider("key").importer_shipments("392010", "AE") == []


def test_volza_non_json_degrades_to_empty(monkeypatch):
    _patch(monkeypatch, _Resp(raises=True))
    assert VolzaShipmentsProvider("key").importer_shipments("392010", "AE") == []


def test_volza_unknown_market_degrades_to_empty(monkeypatch):
    # No network call is even attempted for a market without an ISO3 mapping.
    def _boom(*a, **k):
        raise AssertionError("no HTTP call expected")

    monkeypatch.setattr(httpx, "Client", _boom)
    assert VolzaShipmentsProvider("key").importer_shipments("392010", "ZZ") == []

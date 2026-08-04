"""Live Comtrade routes through the engine's hardened data layer (locked decision #5).

Offline (``COMTRADE_OFFLINE=1`` — the CI/demo default) still reads committed
fixtures; these lock the LIVE path: it delegates to ``silk_data_layer.comtrade_trade``
(so live calls inherit its throttle / circuit-breaker / cache-TTL / mirror-fallback)
and, when every year's fetch fails, degrades to fixtures rather than fabricate a
figure (I1). No network: ``comtrade_trade`` is monkeypatched.
"""

from __future__ import annotations

from datetime import UTC, datetime

import silk_data_layer

from app.providers.shipments.comtrade import ComtradeProvider


def _rec(year: int, partner_code: str, value: float) -> dict:
    return {
        "period": year,
        "refYear": year,
        "partnerCode": partner_code,
        "primaryValue": value,
    }


def test_live_path_delegates_to_data_layer(monkeypatch, tmp_path):
    calls: list[tuple] = []

    def fake_comtrade_trade(hs_code, reporter_m49, year, flow="M", partner=0):
        calls.append((hs_code, reporter_m49, year, flow, partner))
        # Real partners only (no World row) → a clean per-year total.
        return [_rec(year, "276", 200.0), _rec(year, "156", 100.0)]

    monkeypatch.setattr(silk_data_layer, "comtrade_trade", fake_comtrade_trade)

    provider = ComtradeProvider(api_key="k", offline=False, cache_dir=tmp_path)
    flows = provider.trade_flows("080410", "SA", years=3)

    # The live path went through the engine layer — once per year, for imports.
    assert calls, "live Comtrade must delegate to silk_data_layer.comtrade_trade"
    assert {c[2] for c in calls} == {datetime.now(UTC).year - o for o in (1, 2, 3)}
    assert all(c[3] == "M" for c in calls)  # imports into the target market
    assert flows and all(f.data.value_usd == 300.0 for f in flows)  # 200 + 100


def test_live_top_exporters_exclude_world_and_map_partners(monkeypatch, tmp_path):
    def fake_comtrade_trade(hs_code, reporter_m49, year, flow="M", partner=0):
        # Include the World(0) aggregate — it must be excluded from the shares.
        return [_rec(year, "0", 300.0), _rec(year, "276", 200.0), _rec(year, "156", 100.0)]

    monkeypatch.setattr(silk_data_layer, "comtrade_trade", fake_comtrade_trade)

    provider = ComtradeProvider(api_key="k", offline=False, cache_dir=tmp_path)
    tops = provider.top_exporters("080410", "SA", limit=10)

    isos = [t.data.exporter_iso2 for t in tops]
    assert "DE" in isos and "CN" in isos  # 276 → DE, 156 → CN
    # World(0) excluded → shares over real partners only (200 + 100), not halved.
    de = next(t for t in tops if t.data.exporter_iso2 == "DE")
    assert de.data.share_pct == round(100 * 200 / 300, 2)


def test_all_years_failed_degrades_to_fixtures_not_fabrication(monkeypatch, tmp_path):
    # comtrade_trade returns None on a failed fetch; an empty cache dir has no
    # fixture, so the safe result is [] — a declared gap, never a fabricated
    # number (I1).
    monkeypatch.setattr(silk_data_layer, "comtrade_trade", lambda *a, **k: None)

    provider = ComtradeProvider(api_key="k", offline=False, cache_dir=tmp_path)
    assert provider.trade_flows("999999", "SA", years=3) == []
    assert provider.top_exporters("999999", "SA", limit=10) == []

"""LIVE World Bank / WITS market-enrichment adapter (funnel Stage 2), config-switched.

The deterministic mock (``MockMarketEnrichmentProvider``) is the offline/CI default;
this adapter is selected only when ``MARKET_ENRICHMENT_LIVE`` is set, so CI/offline
stays green on zero keys. It does not talk to World Bank / WITS directly: every live
fetch routes through the engine's hardened data layer (locked decision #5) —

* **PPP** via ``silk_data_layer.world_bank(iso3, "NY.GNP.PCAP.PP.CD")`` (GNI per
  capita, PPP, current international $), and
* **applied tariff** via the engine's ``TariffsAgent`` (WTO TTD → WITS fallback →
  declared gap).

Routing through that layer means provenance, per-host throttling, the circuit
breaker, and per-source cache TTL are all inherited; this thin adapter has none of
them of its own.

Never fabricates (I1): a signal that cannot be fetched stays ``None`` (a declared
gap), and when *both* signals fail the whole fetch returns ``None`` so the caller
records the gap rather than storing a fabricated number. Every engine call is wrapped
in broad degradation (mirrors the Comtrade adapter): failure logs and returns ``None``,
never raises.

Unit note: the engine's tariff value is a **percent** (its docstring: "Returns
DataPoint(value=percent)"; its summary line: ``applied tariff {value}% into …``), so
it is divided by 100 to match ``MarketEnrichment.applied_tariff_pct``, which is a
fraction (0.05 = 5%).
"""

from __future__ import annotations

import datetime

from app.logging import get_logger
from app.providers.base import MarketEnrichment, ProviderRecord, SourceType

log = get_logger(__name__)

#: World Bank indicator: GNI per capita, PPP (current international $).
_PPP_INDICATOR = "NY.GNP.PCAP.PP.CD"

#: Confidence when at least one signal is present but neither engine DataPoint
#: carried a confidence (defensive fallback; the engine normally sets one).
_DEFAULT_CONFIDENCE = 0.6


class WorldBankWitsEnrichmentProvider:
    """Applied tariff (WTO/WITS) + PPP GNI per capita (World Bank), per (importer, hs6).

    Routes through ``silk_data_layer`` / the engine ``TariffsAgent`` so provenance,
    throttle, circuit-breaker, and cache are inherited (locked decision #5); never
    fabricates a value (I1).
    """

    name = "market_enrichment_worldbank_wits"

    def enrich_market(
        self, importer_iso3: str, hs6: str
    ) -> ProviderRecord[MarketEnrichment] | None:
        """Fetch applied tariff (fraction) + PPP for one market; a full gap → ``None``.

        Each signal is fetched independently and degraded to ``None`` on any failure
        (I1). If **both** are ``None`` the whole fetch is a declared gap and returns
        ``None`` so the caller records the gap (matches the Protocol and the Stage-2
        service's ``None`` handling). If at least one signal is present, wraps both
        (present + gap) in a ``ProviderRecord`` tagged ``SourceType.ENRICHMENT``.
        """
        tariff_pct, tariff_conf = self._fetch_tariff(importer_iso3, hs6)
        ppp, ppp_conf = self._fetch_ppp(importer_iso3)

        if tariff_pct is None and ppp is None:
            # Both signals failed → full declared gap (I1). Never a fabricated number.
            return None

        confidences = [c for c in (tariff_conf, ppp_conf) if c is not None]
        confidence = max(confidences) if confidences else _DEFAULT_CONFIDENCE
        return ProviderRecord(
            data=MarketEnrichment(
                applied_tariff_pct=tariff_pct,
                ppp_gni_per_capita=ppp,
            ),
            source=SourceType.ENRICHMENT,
            provider_name=self.name,
            confidence=confidence,
        )

    # -- internals ---------------------------------------------------------

    def _fetch_tariff(self, importer_iso3: str, hs6: str) -> tuple[float | None, float | None]:
        """Applied import tariff into the market for ``hs6``, normalised to a FRACTION.

        The engine's ``TariffsAgent`` (WTO TTD → WITS → declared gap) returns the rate
        as a **percent** in ``report.findings[0].value``; divide by 100 to match
        ``MarketEnrichment.applied_tariff_pct`` (fraction). ``value is None`` (a
        declared gap) → ``(None, None)``. Any exception is degraded to ``(None, None)``
        (broad guard, mirrors the Comtrade adapter) — never raises.
        """
        try:
            import silk_tariffs_agent

            # WITS tariff data lags trade data; a recent-but-published year avoids a
            # not-yet-published gap. The agent defaults its own year when omitted.
            year = datetime.date.today().year - 1
            report = silk_tariffs_agent.TariffsAgent().run(
                {"hs_code": hs6, "iso3": importer_iso3, "year": year}
            )
            dp = report.findings[0] if report.findings else None
            if dp is None or dp.value is None:
                return None, None
            return float(dp.value) / 100.0, dp.confidence
        except Exception as exc:  # noqa: BLE001 — engine/WITS volatile; never raise
            log.warning(
                "market_enrichment_tariff_failed",
                importer=importer_iso3,
                hs6=hs6,
                error=str(exc),
            )
            return None, None

    def _fetch_ppp(self, importer_iso3: str) -> tuple[float | None, float | None]:
        """PPP GNI per capita via ``silk_data_layer.world_bank`` (routes through the layer).

        ``DataPoint.value is None`` on any World Bank miss/failure → ``(None, None)``
        (declared gap, I1). Any exception is degraded to ``(None, None)`` — never raises.
        """
        try:
            import silk_data_layer

            dp = silk_data_layer.world_bank(importer_iso3, _PPP_INDICATOR)
            if dp.value is None:
                return None, None
            return float(dp.value), dp.confidence
        except Exception as exc:  # noqa: BLE001 — WB layer volatile; never raise
            log.warning(
                "market_enrichment_ppp_failed",
                importer=importer_iso3,
                error=str(exc),
            )
            return None, None

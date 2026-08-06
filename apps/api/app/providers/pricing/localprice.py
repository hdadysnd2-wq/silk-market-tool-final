"""LIVE observed-price adapter — the paid local-price layer, config-switched (I5 + I1).

The deterministic mock (``MockPriceProvider``) is the offline/CI default; this
adapter is selected only when the vendor key is configured (``LOCALPRICE_API_KEY``
— the same key the engine agent reads), so CI/offline stays green on zero keys. It
does not talk to a shopping/price API directly: every fetch routes through the
engine's PAID ``LocalPriceAgent``
(``silk_localprice_agent``), so provenance and the engine's own paid/deepen guard
are inherited — this thin adapter has neither of its own.

Deepen-gating (I5) lives at the service (``services.observed_prices``), which never
calls the provider outside the deepen scope; the engine agent's ``PAID`` guard is a
belt-and-suspenders second line (called outside deepen it returns a skipped report
with no vendor call). This adapter is therefore only ever reached inside deepen.

Never fabricates (I1): only observed listings that carry a real price become
records; a finding with no usable price (the no-key / no-results / failure case,
where the engine returns ``DataPoint(None, …)``) is dropped as a declared gap. An
empty return is honest ("no observed listings"), never a guessed number. The whole
fetch is wrapped in broad degradation (mirrors the Comtrade adapter): any engine or
vendor hiccup logs and returns ``[]`` — never raises into the deepen run.

Search query: the engine agent searches a shopping API by a free-text product
query, so the caller passes the product name (``product_name``) — a Google
Shopping search for "392010" returns nothing useful. The HS6 code is only a
last-resort fallback when no name is available.

Import stays pandas-free (I7): the engine agent is lazy-imported inside the method,
so importing this module has no heavy side effects.
"""

from __future__ import annotations

from app.logging import get_logger
from app.providers.base import ObservedPrice, ProviderRecord, SourceType

log = get_logger(__name__)


class LocalPriceProvider:
    """Observed competitor prices via the engine's PAID ``LocalPriceAgent``.

    Routes through ``silk_localprice_agent.LocalPriceAgent`` so provenance and the
    paid/deepen guard are inherited (the only caller runs inside deepen). Never
    fabricates a price (I1): findings without a usable observed price are dropped.
    """

    name = "localprice_serper"

    def observed_prices(
        self,
        hs_code: str,
        market_iso2: str,
        limit: int = 10,
        product_name: str | None = None,
    ) -> list[ProviderRecord[ObservedPrice]]:
        """Observed retail listings for one (product, market), as provenance records.

        Delegates to the engine's ``LocalPriceAgent`` (``PAID = True``): each priced
        listing it returns is a ``DataPoint(value={title, price, currency, store,
        link})``; a no-key / no-results / failure case is a single
        ``DataPoint(None, …)`` which is dropped here (a declared gap, never a
        fabricated price — I1). The search query is the product NAME (an HS6 code
        is not a shopping query); it falls back to ``hs_code`` only when no name is
        available. Any exception degrades to ``[]`` (mirrors the Comtrade adapter) —
        a vendor hiccup never crashes the deepen run and never fabricates.
        """
        query = (product_name or "").strip() or hs_code
        try:
            from silk_localprice_agent import LocalPriceAgent

            report = LocalPriceAgent().run({"query": query, "market": market_iso2})
            out: list[ProviderRecord[ObservedPrice]] = []
            for dp in report.findings:
                v = dp.value
                # I1 — observed listings only: a non-dict value or a missing price
                # is a declared gap (the engine's None-finding case), never a
                # fabricated number.
                if not isinstance(v, dict) or v.get("price") is None:
                    continue
                out.append(
                    ProviderRecord(
                        data=ObservedPrice(
                            competitor=v.get("title") or "",
                            price=float(v["price"]),
                            currency=v.get("currency") or "USD",
                            url=v.get("link"),
                            store=v.get("store"),
                        ),
                        source=SourceType.ENRICHMENT,
                        provider_name=self.name,
                        confidence=dp.confidence,
                    )
                )
                if len(out) >= limit:
                    break
            return out
        except Exception as exc:  # noqa: BLE001 — engine/vendor volatile; never raise
            log.warning(
                "localprice_fetch_failed",
                hs_code=hs_code,
                market=market_iso2,
                error=str(exc),
            )
            return []

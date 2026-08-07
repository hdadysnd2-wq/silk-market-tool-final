# ADR-0005 — Real observed-price sources for the executive report

- **Status:** Proposed (owner decision required)
- **Date:** 2026-08-07
- **Deciders:** Owner
- **Relates to:** audit 2026-08-07 C3 (`app/providers/pricing/gated.py`) · invariants I1 (no fabrication) / I5 (paid = deepen-gated)

## Context

The executive report's per-market prices section needs REAL competitor prices.
The 2026-08-07 audit (C3) found a keyless production deploy persisting the mock
provider's invented listings as "observed"; the slot now fails closed: with no
`LOCALPRICE_API_KEY` outside `local`, the registry returns `GatedPriceProvider`
and the report shows a declared gap. Honest — but every keyless production
report ships with an empty prices section. A real source must be chosen.

## Options

### (a) SerpApi Google Shopping via the EXISTING live adapter

`apps/api/app/providers/pricing/localprice.py` → engine
`silk_localprice_agent.py` is already built, tested, and deepen-gated (I5,
PAID guard). Default endpoint is `https://serpapi.com/search.json` with
`engine=google_shopping`; it searches by product NAME and keeps only listings
carrying a real price (I1).

- **Cost:** SerpApi per-search subscription tiers — roughly US$75/mo for ~5,000
  searches at entry level, rising with volume (see serpapi.com/pricing). One
  deepen run consumes one search per market.
- **Effort:** key only — set `LOCALPRICE_API_KEY`. Zero code.
- **Latency:** seconds per market, inside the deepen run.
- **Coverage:** retail listings with URLs/store names; strong in markets Google
  Shopping serves (EU, US, GCC), weak/empty elsewhere.

### (b) UN Comtrade unit values as wholesale benchmarks

`etl/world_trade_sync` already writes `import_usd` AND `import_qty` per
(hs6, importer, year) into `world_trade`. `import_usd / import_qty` is a
per-country WHOLESALE unit-value benchmark — free, universal, already synced.

- **Cost:** free (Comtrade); live refresh needs the existing `COMTRADE_API_KEY`.
- **Effort:** small product-side computation + honest label — this is a
  "trade-statistics unit value, not retail", and must render as such.
- **Latency:** none at report time (reads persisted rows).
- **Coverage:** every market that reports quantities to Comtrade — near-global,
  but a customs average, not a shelf price.

### (c) Licensed / marketplace sources

Amazon SP-API per marketplace (requires a seller account + API approval;
coverage limited to Amazon marketplaces), or a licensed retail-price dataset
(Euromonitor/Numbeo-class subscriptions).

- **Cost:** highest — seller registration and/or annual license fees.
- **Effort:** account approval workflows, new adapters, contract negotiation.
- **Latency/coverage:** best comparability and data quality where licensed, but
  months to first data.

## Recommendation

**Ship (a) + (b) together — retail observations where SerpApi covers, the
Comtrade unit-value benchmark everywhere, each labeled with its own source; (c)
is deferred until a licensed-data budget exists.**

The two are complementary, not redundant: (a) gives client-visible retail
listings with URLs in covered markets; (b) guarantees no market's prices
section is ever structurally empty, at the cost of an explicitly-labeled
wholesale proxy. Both keep I1 — nothing is fabricated, every figure carries its
source — and (a) stays inside the existing I5 deepen gate, so spend is
per-request and capped.

## Keys / decisions the owner must provide

1. `LOCALPRICE_API_KEY` — a SerpApi key, and which pricing tier (monthly search
   budget) to subscribe to.
2. Confirm `LOCALPRICE_API_URL` stays on the SerpApi default (only needed if a
   different shopping-JSON vendor is chosen).
3. `COMTRADE_API_KEY` — already required for the live `world_trade` sync; unit
   values ride the same sync (no extra key).
4. Approve the unit-value label wording on the client surface
   ("trade-statistics unit value, not retail") — it must never read as a shelf
   price.
5. Defer/approve (c): whether to start Amazon SP-API seller onboarding or a
   licensed-dataset trial this quarter (recommendation: defer).

## Consequences

- Until key №1 arrives, keyless production keeps the C3 declared gap — now
  rendered as "pricing pending data source" (see J3), not a generic empty state.
- (b) adds a small product-side computation and no new provider slot; it must
  not be wired through the observed-prices (retail) path or the labels blur.
- Revisit (c) only with a budget owner and a named marketplace list.

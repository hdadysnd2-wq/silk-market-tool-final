# etl/ — offline bulk data jobs

**pandas and `comtradeapicall` are allowed HERE ONLY** (locked decision #5, invariant I7).
Everything in this directory runs *offline*, on a schedule (monthly/quarterly) or
by hand — never in the hot request path. The CI guard `tools/check_no_pandas.py`
deliberately does not scan this directory.

## Jobs

| Script | Purpose | Writes |
|--------|---------|--------|
| `world_trade_sync.py` | Bulk-download world import flows per HS6 from UN Comtrade and compute YoY / 3-yr CAGR, tagging transit-hub re-export inflation and mirror-data rows. | `world_trade` table (Postgres) |
| `hs_reference_sync.py` | Refresh the official HS6 reference used by the classifier's confirm step. | `hs_reference` table / `data/hs_reference.csv` |

## Why a separate ETL layer (not the request path)

Stage 1 of the 3-stage world funnel — "screen every country locally, zero live
API calls" — is a single SQL query against a **precomputed** `world_trade`
table. These jobs are what precompute it. Bulk Comtrade pulls are exactly the
workload `comtradeapicall` + pandas are good at, and keeping them offline means:

- the request path never blocks on Comtrade,
- the ~500 req/day live Comtrade budget is spent on Stage 2/3 enrichment only,
- provenance is still recorded per row (`source`, `fetched_at`, `is_mirror`).

Live Comtrade calls (Stages 2–3) do **not** run here — they go through the
engine's hand-rolled `silk_data_layer` (throttling, circuit breaker, cache TTL,
mirror fallback, provenance), which the thin `comtradeapicall` wrapper lacks.

## Status

Phase 0 ships these as **documented skeletons**. The live `world_trade` table,
its migration, the Stage-1 query and the transit-port guard land in **Phase 2**;
first real live sync lands in **Phase 3** (after a Comtrade key is provisioned).
The skeletons import their heavy deps lazily inside `run()` so the module is
importable — and the no-pandas guard is satisfied for the rest of the repo —
without pandas/comtradeapicall installed.

## Running (once implemented)

```bash
pip install -r etl/requirements.txt
export COMTRADE_API_KEY=...           # Phase 3
export DATABASE_URL=postgresql+psycopg://silk:silk@localhost:5432/silk
python -m etl.world_trade_sync --years 2021 2022 2023
python -m etl.hs_reference_sync
```

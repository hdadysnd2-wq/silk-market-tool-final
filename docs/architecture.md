# Silk United — Monorepo Architecture

One product, one repo. A factory uploads a product image → the system proposes an
HS code (human confirms) → scans every world market and funnels to the top 5
export countries → lists competitors with observed prices per country → produces
verified buyer lists → drafts outreach in the buyer's language → sends **only**
after explicit human approval, with tracking.

This document records the merge architecture and the Phase 0 scaffold. The full
mission, invariants and phased plan live in the master prompt (`docs/MASTER_PROMPT.md`).

## Two repos → one modular monolith

| Source | Role | Landed at |
|--------|------|-----------|
| **Silk-market-intelligence** (Repo A — the *brain*) | Mature multi-agent Python market-intelligence engine: `DataPoint` provenance model, HS resolver + human confirm, transparent market ranker, correlation/discovery agents, unified render → brief + Word report, hand-rolled Comtrade/World-Bank data layer (throttling, circuit breaker, cache, mirror fallback). | `packages/silk_intel/` |
| **silk-market-tool-** (Repo B — the *body*) | Product shell + campaign machinery: FastAPI + Celery + SQLAlchemy + Alembic + Postgres/pgvector + Redis; Next.js (App Router, Arabic RTL-first, next-intl); provider abstraction with deterministic mocks for every vendor; 3-layer human send-approval; suppression list; append-only audit log; per-factory OAuth sending; deliverability/warm-up. | `apps/api/`, `apps/web/`, `infra/` |

**Not microservices.** The engine is an in-process installable package the Celery
workers import directly — no HTTP hop (locked decision #2).

## Layout

```
silk-market-tool-final/
├── apps/
│   ├── api/            # Repo B backend: FastAPI + Celery + Alembic (package `app`)
│   └── web/            # Repo B frontend: Next.js App Router, RTL-first
├── packages/
│   ├── silk_intel/     # Repo A engine (installable) + its hermetic test suite
│   │   ├── silk_intel/ # engine modules (flat namespace) + data/ + tools/ + tests/
│   │   ├── conftest.py # puts engine dir on sys.path, anchors cwd for data/
│   │   └── pyproject.toml
│   └── contracts/      # unified DataPoint/ProviderRecord envelope (decision #4)
├── etl/                # offline bulk jobs — pandas + comtradeapicall ALLOWED HERE ONLY (I7)
├── infra/              # docker-compose.dev.yml + Terraform (me-south-1) + Railway configs
├── docs/               # this file, VISION, EXECUTION_PLAN, MASTER_PROMPT, provenance
├── tools/              # check_no_pandas.py (I7 CI guard)
├── Makefile            # make dev / demo / test / lint / etl
└── .github/workflows/ci.yml   # guard-pandas + silk_intel + api + web + e2e
```

## Two deliberate deviations from the target diagram

Both preserve a **hard merge invariant** ("move the engine's tests unchanged")
over an illustrative layout detail. Recorded here so they are intentional, not
drift:

1. **Engine tests live beside the engine modules** — `packages/silk_intel/silk_intel/tests/`,
   not `packages/silk_intel/tests/`. Repo A's suite hardcodes repo-root-relative
   paths (`dirname(dirname(__file__))/tools/...`, root-level helper modules like
   `canonical_fettuccine`, and a few modules that open `data/*.csv` relative to
   cwd — e.g. `silk_hs_confirm`). Keeping tests as a sibling of the modules — the
   exact Repo A relationship, one directory deeper — lets **every one of the
   2,500+ tests run byte-identical**. Separating them by an extra level broke 4
   collection paths; nesting them fixes it with zero test edits. The package
   wrapper (`pyproject.toml`, `conftest.py`, `README.md`) sits one level up.

2. **The pandas guard scopes to source, not test trees.** Invariant I7 bans
   pandas outside `etl/`. Engine *code* imports no pandas; only two Google-Trends
   *test fixtures* build mock `DataFrame`s, because the runtime dependency
   `pytrends` returns DataFrames (pandas thus arrives transitively). The guard
   (`tools/check_no_pandas.py`) enforces I7 on `apps/**` and the engine source,
   excluding test trees — honoring I7's real intent (no pandas in the hot path)
   while keeping the vendored tests unchanged.

## Invariants enforced from Phase 0

- **I1 — no fabricated data.** The unified contract (`packages/contracts`) makes
  "no data" a first-class state: `value=None, confidence=0.0` + a note. The
  engine's `DataPoint` already embodies this; `contracts` unifies it with Repo
  B's `ProviderRecord`.
- **I7 — pandas confined to `etl/`.** CI job `guard-pandas` runs on every push.
- Invariants I2 (HS human-confirm), I3 (3-layer send approval), I4 (suppression +
  audit), I5 (paid agents only in deepen), I6 (no cold email via transactional
  ESP), I8 (consent basis), I9 (transit-port guard), I10 (Arabic RTL) are carried
  by the vendored code and are wired/tested progressively in Phases 1–3.

## Storage & contracts (Phase 1 targets, scaffolded now)

Storage unifies on **Postgres + Redis**; the engine's SQLite + disk cache are
replaced behind its existing `silk_storage` interface (strangler shim, no
big-bang). `DataPoint` + `ProviderRecord` converge on one envelope
(`packages/contracts`) — defined now, consumed in Phase 1 with deprecation shims.

## Data sources (locked verdicts)

- **Live Comtrade / World Bank** → the engine's hand-rolled `silk_data_layer`
  (provenance, throttling, circuit breaker, cache TTL, mirror fallback).
- **Bulk Comtrade** (`comtradeapicall` + pandas) → `etl/` only, offline, to
  precompute the `world_trade` table for funnel Stage 1.
- **Meilisearch** → deferred (HS stays difflib + human confirm; app search uses
  Postgres FTS/`pg_trgm`). **warmbly** → rejected (Smartlead/Instantly + OAuth).

## Build / run / test

```bash
make dev     # boot the whole stack offline on mocks, zero API keys
make demo    # golden-path pipeline, prints each step
make test    # pandas guard + engine suite + api (ruff+pytest) + web (lint+build)
make lint    # ruff + pandas guard + eslint
make etl     # offline bulk jobs (pandas/comtradeapicall live here only)
```

CI (`.github/workflows/ci.yml`) runs the same five checks: `guard-pandas`,
`silk_intel`, `api`, `web`, `e2e`.

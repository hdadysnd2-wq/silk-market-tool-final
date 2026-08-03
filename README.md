# Silk United (سِلك) — Export Intelligence Platform

A single product for a licensed Saudi export house: **upload a product image →
confirm the proposed HS code → screen every world market down to the top 5
export countries → see competitors and observed prices per country → build a
verified buyer list → review an AI-drafted outreach email in the buyer's
language → approve → send and track.** Every number carries its source; every
send is human-approved and audited; the whole system boots offline on mocks.

This monorepo merges two repositories into one modular monolith:

- **the brain** — the mature market-intelligence engine (`packages/silk_intel/`),
- **the body** — the product shell, campaign machinery and Arabic RTL web app
  (`apps/api/`, `apps/web/`).

See [`docs/architecture.md`](docs/architecture.md) for the full design and
[`docs/MASTER_PROMPT.md`](docs/MASTER_PROMPT.md) for the mission, invariants and
phased plan.

## Quick start (offline, zero API keys)

```bash
make dev     # Postgres + Redis + MinIO + api + worker + beat + web, all on mocks
make demo    # run the golden-path pipeline end to end and print each step
```

`make dev` creates `.env` from `.env.example` on first run — every vendor key is
optional and blank keys select a deterministic mock adapter.

## Repository layout

```
apps/api/        FastAPI + Celery + Alembic (package `app`)
apps/web/        Next.js App Router, RTL-first (next-intl ar/en)
packages/silk_intel/   market-intelligence engine (installable) + hermetic tests
packages/contracts/    unified provenance envelope (DataPoint/ProviderRecord)
etl/             offline bulk jobs — pandas + comtradeapicall live HERE only
infra/           docker-compose.dev.yml + Terraform (me-south-1) + Railway
docs/            architecture, vision, execution plan, master prompt
tools/           check_no_pandas.py (CI guard)
```

## Tests & CI

```bash
make test    # pandas guard + engine suite + api (ruff+pytest) + web (lint+typecheck+build)
```

One CI pipeline (`.github/workflows/ci.yml`) runs five jobs: `guard-pandas`,
`silk_intel` (engine hermetic suite), `api`, `web`, and `e2e` (Playwright against
mocked APIs).

## Status

**Phase 0 — scaffold & freeze.** The monorepo layout is in place, both source
repos are vendored, the engine's hermetic suite runs green, and the stack boots
offline on mocks. Storage unification, contract merge, and end-to-end pipeline
wiring follow in Phases 1–3 (see `docs/EXECUTION_PLAN.md` and the master prompt).

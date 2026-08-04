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

## Deploy (Railway)

One repo, four services (`api`, `worker`, `beat`, `web`) sharing one Postgres and
one Redis. A single script provisions the whole project:

```bash
./deploy-to-railway.sh            # infers the repo from your git remote
```

It installs the Railway CLI, creates the project, provisions the databases, and
creates the four GitHub-linked services with their shared variables wired as
Railway reference variables — then prints the two dashboard settings the CLI
can't set (each service's root directory + config path). Full runbook:
[`docs/DEPLOY_RAILWAY.md`](docs/DEPLOY_RAILWAY.md).

## Tests & CI

```bash
make test    # pandas guard + engine suite + api (ruff+pytest) + web (lint+typecheck+build)
```

One CI pipeline (`.github/workflows/ci.yml`) runs five jobs: `guard-pandas`,
`silk_intel` (engine hermetic suite), `api`, `web`, and `e2e` (Playwright against
mocked APIs).

## Status

`main` is the single source of truth — see
[`docs/adr/0001-master-prompt-governs.md`](docs/adr/0001-master-prompt-governs.md).

- **Phase 0 — scaffold & freeze:** complete. Monorepo layout in place, both repos
  vendored, engine hermetic suite green, stack boots offline on mocks.
- **Phase 1 — contracts + engine wiring:** the unified contract envelope is in
  place and the Celery workers call the engine for HS resolve + rank with the
  deepen guard ported. Storage: the product shell persists to Postgres + Redis;
  the engine-side `silk_storage` → Postgres adapter is still open (locked
  decision #3 is only partially done — tracked in
  [`docs/BACKLOG.md`](docs/BACKLOG.md)).
- **Phase 2 — full pipeline on mocks + funnel Stage 1 + UX:** substantially
  complete on mocks (image → HS-confirm → world screen → top 5 with transit
  flags → competitors → leads → draft → 3-layer approval → tracked send). The
  funnel's Stage 3 deep-dive is not yet wired.
- **Phase 3 — go live, one key at a time:** not started. Real provider adapters
  exist but are unproven against live APIs — see
  [`docs/PHASE3_ADAPTER_READINESS.md`](docs/PHASE3_ADAPTER_READINESS.md).

The invariants (I1–I10) are implemented and covered by tests. See
[`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md) and the master prompt for the
full plan.

# Silk United monorepo — one entry point for the whole product.
#
#   make dev    boot the full stack offline on mocks (Postgres+Redis+MinIO+api+worker+beat+web)
#   make demo   run the golden-path pipeline end to end and print each step
#   make test   backend + frontend + engine tests + the pandas-import guard
#   make lint   ruff (api) + pandas guard + eslint (web)
#   make etl    show the offline ETL jobs (pandas/comtradeapicall live here only)

COMPOSE := docker compose -f infra/docker-compose.dev.yml --project-directory .

.PHONY: help dev up down migrate seed demo test test-api test-web test-intel \
        test-contracts lint lint-api lint-web guard-pandas etl logs api-shell env

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing (zero-key mock defaults)
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example (all mocks).")

up: env ## Build and start all services
	$(COMPOSE) up -d --build
	@echo "Waiting for the API to become healthy…"
	@until curl -sf http://localhost:8000/health >/dev/null 2>&1; do sleep 2; done
	@echo "API ready at http://localhost:8000/docs  ·  Web at http://localhost:3000"

down: ## Stop all services
	$(COMPOSE) down

migrate: ## Apply database migrations
	$(COMPOSE) exec api alembic upgrade head

seed: ## Seed reference data, demo users, and pilot sectors (idempotent)
	$(COMPOSE) exec api python -m app.seeds.seed

dev: up migrate seed ## One-shot: up + migrate + seed (offline, no keys)
	@echo "Stack up, migrated, seeded. Log in at http://localhost:3000 with factory1@demo.silk / Demo1234!"

demo: ## Run the golden-path demo end to end and print each step
	$(COMPOSE) exec api python -m app.seeds.demo_golden_path

# ---- tests -----------------------------------------------------------------

test: guard-pandas test-contracts test-intel test-api test-web ## Everything CI runs, locally

test-api: ## Backend (apps/api) ruff + pytest
	cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run pytest -q

test-web: ## Frontend (apps/web) lint + typecheck + build
	cd apps/web && pnpm lint && pnpm typecheck && pnpm build

test-intel: ## Vendored engine hermetic suite (packages/silk_intel)
	cd packages/silk_intel && uv run --no-project \
		--with pytest --with httpx --with-requirements silk_intel/requirements.txt \
		python -m pytest

test-contracts: ## Unified data-contract package tests (packages/contracts)
	cd packages/contracts && uv run --no-project --with pytest python -m pytest tests -q

# ---- lint ------------------------------------------------------------------

lint: guard-pandas lint-api lint-web ## Lint/format-check everything + pandas guard

lint-api:
	cd apps/api && uv run ruff check . && uv run ruff format --check .

lint-web:
	cd apps/web && pnpm lint

guard-pandas: ## Invariant I7 — fail if pandas is imported outside etl/
	python3 tools/check_no_pandas.py

# ---- etl -------------------------------------------------------------------

etl: ## Offline bulk jobs (pandas + comtradeapicall allowed HERE only, I7)
	@echo "Offline ETL jobs (see etl/README.md). Install deps: pip install -r etl/requirements.txt"
	@echo "  python -m etl.world_trade_sync --hs6 <code> --years 2021 2022 2023"
	@echo "  python -m etl.hs_reference_sync"

# ---- misc ------------------------------------------------------------------

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

api-shell: ## Open a shell in the running API container
	$(COMPOSE) exec api bash

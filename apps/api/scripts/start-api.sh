#!/usr/bin/env sh
# Entrypoint for the API service on Railway (and any managed platform).
#
# Runs database migrations, optionally seeds demo data, then launches the API
# bound to the platform-assigned $PORT. Migrations live here — not in the worker
# or beat start scripts — so schema changes are applied exactly once per deploy.
set -e

echo "[start-api] applying database migrations…"
if ! alembic upgrade head; then
  echo "[start-api] ERROR: database migrations failed — the API cannot start." >&2
  echo "[start-api] Most common cause on a managed platform: the Postgres database has" >&2
  echo "[start-api] no pgvector extension. The first migration runs" >&2
  echo "[start-api] 'CREATE EXTENSION IF NOT EXISTS vector'; a plain Postgres image fails it." >&2
  echo "[start-api] Fix: provision a pgvector-enabled Postgres (e.g. the pgvector/pgvector" >&2
  echo "[start-api] image) and confirm DATABASE_URL points at it. See docs/DEPLOY_RAILWAY.md." >&2
  exit 1
fi

# Seed reference data + demo accounts on boot. The seed is idempotent (every
# insert is existence-guarded), so it is safe to re-run on every deploy. Set
# RUN_SEED=0 to skip it once you have real data you don't want re-seeded.
if [ "${RUN_SEED:-1}" = "1" ]; then
  echo "[start-api] seeding reference + demo data (RUN_SEED=1)…"
  python -m app.seeds.seed || echo "[start-api] seed step failed; continuing to start the API"
fi

echo "[start-api] starting uvicorn on 0.0.0.0:${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

#!/usr/bin/env sh
# Entrypoint for the API service on Railway (and any managed platform).
#
# Runs database migrations, optionally seeds demo data, then launches the API
# bound to the platform-assigned $PORT. Migrations live here — not in the worker
# or beat start scripts — so schema changes are applied exactly once per deploy.
set -e

# Settings are validated before anything touches the database. Alembic's env.py
# instantiates Settings() too, so a missing required variable (e.g.
# TOKEN_ENCRYPTION_KEY with ENVIRONMENT=production) used to surface as a
# "migration failure" and get misdiagnosed as a database problem. Pydantic's
# error message names the exact variable and how to generate it.
echo "[start-api] validating configuration…"
if ! python -c "from app.config import get_settings; get_settings()"; then
  echo "[start-api] ERROR: configuration is invalid — the API cannot start." >&2
  echo "[start-api] The validation error above names the environment variable to fix." >&2
  echo "[start-api] Set it on THIS service (Railway → service → Variables) and on the" >&2
  echo "[start-api] worker/beat services, which share the same settings. This is a" >&2
  echo "[start-api] configuration problem, NOT a database problem. See the" >&2
  echo "[start-api] Troubleshooting section of docs/DEPLOY_RAILWAY.md." >&2
  exit 1
fi

echo "[start-api] applying database migrations…"
MIG_LOG=$(mktemp)
MIG_STATUS=$(mktemp)
# Stream migration output live while capturing it for diagnosis. $? after a
# pipeline is tee's status, so alembic's own status is smuggled out via a file.
{ alembic upgrade head 2>&1; echo "$?" >"$MIG_STATUS"; } | tee "$MIG_LOG"
if [ "$(cat "$MIG_STATUS")" != "0" ]; then
  echo "[start-api] ERROR: database migrations failed — the API cannot start." >&2
  if grep -Eqi 'could not open extension control file|extension "vector" is not available|type "vector" does not exist' "$MIG_LOG"; then
    echo "[start-api] Diagnosis: the Postgres database has no pgvector extension." >&2
    echo "[start-api] The first migration runs 'CREATE EXTENSION IF NOT EXISTS vector';" >&2
    echo "[start-api] a plain Postgres image fails it. Fix: provision a pgvector-enabled" >&2
    echo "[start-api] Postgres (e.g. the pgvector/pgvector image) and confirm DATABASE_URL" >&2
    echo "[start-api] points at it. See docs/DEPLOY_RAILWAY.md." >&2
  elif grep -Eqi 'connection refused|could not translate host name|name or service not known|timeout expired|connection timed out|password authentication failed|is the server running' "$MIG_LOG"; then
    echo "[start-api] Diagnosis: the database is unreachable (or refused the credentials)." >&2
    echo "[start-api] Confirm DATABASE_URL points at a running Postgres this service can" >&2
    echo "[start-api] reach — on Railway it should be the \${{Postgres.DATABASE_URL}}" >&2
    echo "[start-api] reference variable. See docs/DEPLOY_RAILWAY.md." >&2
  else
    echo "[start-api] The traceback above is the actual cause — read it before assuming" >&2
    echo "[start-api] a database problem. Common causes and fixes are listed in the" >&2
    echo "[start-api] Troubleshooting section of docs/DEPLOY_RAILWAY.md." >&2
  fi
  rm -f "$MIG_LOG" "$MIG_STATUS"
  exit 1
fi
rm -f "$MIG_LOG" "$MIG_STATUS"

# Seed reference data on boot. The seed is idempotent (every insert is
# existence-guarded), so it is safe to re-run on every deploy. Demo accounts
# (shared, well-known password) are planted ONLY when ENVIRONMENT=local — off
# 'local' the seed populates reference data (HS codes, markets) and nothing
# else. Set RUN_SEED=0 to skip it once you have real data you don't want
# re-seeded.
if [ "${RUN_SEED:-1}" = "1" ]; then
  echo "[start-api] seeding reference data (demo accounts only on ENVIRONMENT=local)…"
  python -m app.seeds.seed || echo "[start-api] seed step failed; continuing to start the API"
fi

echo "[start-api] starting uvicorn on 0.0.0.0:${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

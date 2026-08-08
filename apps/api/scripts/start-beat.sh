#!/usr/bin/env sh
# Entrypoint for the Celery beat scheduler service (periodic follow-ups,
# deliverability evaluation, daily counter resets, warmup advancement).
set -e

# Self-contained cwd (see start-worker.sh) — works even when the start command
# is exec'd without a shell, and `celery -A app.workers…` needs this directory.
cd /app/apps/api

echo "[start-beat] starting Celery beat"
exec celery -A app.workers.celery_app.celery_app beat --loglevel=info

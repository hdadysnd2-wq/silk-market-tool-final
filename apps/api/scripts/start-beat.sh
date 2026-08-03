#!/usr/bin/env sh
# Entrypoint for the Celery beat scheduler service (periodic follow-ups,
# deliverability evaluation, daily counter resets, warmup advancement).
set -e

echo "[start-beat] starting Celery beat"
exec celery -A app.workers.celery_app.celery_app beat --loglevel=info

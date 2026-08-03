#!/usr/bin/env sh
# Entrypoint for the Celery worker service. No migrations here — the API service
# owns schema changes; the worker only processes queued tasks.
set -e

echo "[start-worker] starting Celery worker"
exec celery -A app.workers.celery_app.celery_app worker --loglevel=info

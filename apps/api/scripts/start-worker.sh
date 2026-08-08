#!/usr/bin/env sh
# Entrypoint for the Celery worker service. No migrations here — the API service
# owns schema changes; the worker only processes queued tasks.
set -e

# Make the script self-contained: cd into the app dir ourselves rather than
# relying on the caller (`cd X && sh Y`). Some platforms exec the start command
# without a shell, so a leading `cd` in the command line fails with "the
# executable `cd` could not be found" — and `celery -A app.workers…` needs this
# working directory to import the `app` package regardless.
cd /app/apps/api

echo "[start-worker] starting Celery worker"
exec celery -A app.workers.celery_app.celery_app worker --loglevel=info

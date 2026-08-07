FROM python:3.11-slim

# uv for fast, lockfile-based dependency installation.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# IMPORTANT: this image builds from the REPOSITORY ROOT as the Docker build
# context, not from apps/api. apps/api/pyproject.toml declares two editable path
# dependencies that live OUTSIDE apps/api:
#     silk-intel     -> ../../packages/silk_intel
#     silk-contracts -> ../../packages/contracts
# so those sibling packages must exist in the build context. We recreate the
# repo's on-disk layout inside the image (/app/apps/api alongside /app/packages)
# so the ../../packages/* sources resolve exactly as they do in a full checkout.
#
# Build/deploy configuration therefore points the Dockerfile at the root:
#   • Railway   : Root Directory = repo root, Dockerfile path = apps/api/Dockerfile
#                 (see apps/api/railway*.json and docs/DEPLOY_RAILWAY.md)
#   • Compose   : context: . , dockerfile: apps/api/Dockerfile
#                 (see infra/docker-compose.dev.yml)
WORKDIR /app/apps/api

# Sibling path-dependencies first — they change rarely, so this layer caches well.
COPY packages /app/packages

# Enforce the .dockerignore exclusion of the legacy silk_platform product at
# build level: it carries a cold-send queue with no per-email approval gate
# (ADR-0004), so "not shipped" must not depend on ignore-file drift.
RUN test ! -e /app/packages/silk_intel/silk_intel/silk_platform \
    || (echo "silk_platform must not ship in the production image" && exit 1)

# Dependency layer: resolve against the lockfile before app code is copied, so a
# code-only change does not re-install dependencies.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code, then install the project itself.
COPY apps/api/ ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/apps/api/.venv/bin:$PATH"

# Strip any CR line endings (a Windows checkout can introduce them) so the
# scripts run under /bin/sh, then make them executable.
RUN sed -i 's/\r$//' scripts/*.sh && chmod +x scripts/*.sh

# Run the app as a non-root user (least privilege — HIGH-11). Build steps above
# run as root; the runtime process does not. Every writable runtime path lives
# under /app (the celerybeat schedule file, STORAGE_BACKEND=local uploads), so
# chowning /app keeps them writable. If a persistent volume is later mounted
# (e.g. at /app/storage), ensure it is writable by uid 10001.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/storage \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# One image serves all three backend roles; SILK_ROLE selects the entrypoint
# script (api = migrate+seed+uvicorn, worker = celery worker, beat = celery
# scheduler). Defaults to "api". The absolute `cd` makes the command independent
# of the working directory a platform starts it in (Railway runs a service's
# command from the repo-root workdir, not this image's WORKDIR), so no per-service
# start-command override is needed — set SILK_ROLE as a service variable instead.
CMD ["sh", "-c", "cd /app/apps/api && exec sh scripts/start-${SILK_ROLE:-api}.sh"]

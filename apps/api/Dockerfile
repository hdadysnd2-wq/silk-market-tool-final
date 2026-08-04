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

EXPOSE 8000

# Default command runs the API: migrate, seed, then bind uvicorn to $PORT.
# The worker and beat services reuse this same image with an overridden start
# command (scripts/start-worker.sh / scripts/start-beat.sh).
CMD ["sh", "scripts/start-api.sh"]

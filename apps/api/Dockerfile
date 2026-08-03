FROM python:3.11-slim

# uv for fast, lockfile-based dependency installation.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Strip any CR line endings (a Windows checkout can introduce them) so the
# scripts run under /bin/sh, then make them executable.
RUN sed -i 's/\r$//' scripts/*.sh && chmod +x scripts/*.sh

EXPOSE 8000

# Default command runs the API: migrate, seed, then bind uvicorn to $PORT.
# The worker and beat services reuse this same image with an overridden start
# command (scripts/start-worker.sh / scripts/start-beat.sh).
CMD ["sh", "scripts/start-api.sh"]

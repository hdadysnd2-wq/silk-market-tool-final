FROM node:22-slim

# This image builds from the REPOSITORY ROOT as the Docker build context (the
# web app itself has no cross-package dependency, but building from the root lets
# every service leave Railway's "Root Directory" empty and select its Dockerfile
# via the RAILWAY_DOCKERFILE_PATH service variable — a fully headless deploy).
WORKDIR /app

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
# Pin pnpm so the builder's supply-chain policy (release-age cooldown, build-script
# approval) behaves the same as the committed lockfile was resolved against.
RUN corepack enable && corepack prepare pnpm@11.18.0 --activate

# pnpm-workspace.yaml carries the approved-build settings (sharp, unrs-resolver);
# it must be present before install or pnpm 11 aborts on unapproved build scripts.
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY apps/web/ ./

# Next.js resolves rewrite destinations at build time, so the backend URL the
# `/api/*` proxy points at must be known here — not just at runtime. Railway
# passes service variables to the Docker build, so set API_PROXY_TARGET as a
# service variable (e.g. https://your-backend.up.railway.app) before deploying.
ARG API_PROXY_TARGET
ENV API_PROXY_TARGET=${API_PROXY_TARGET}

ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

EXPOSE 3000

# Bind to the platform-assigned $PORT (falls back to 3000 locally). The absolute
# `cd` keeps the command independent of the working directory the platform starts
# it in, mirroring the api image.
CMD ["sh", "-c", "cd /app && exec pnpm start -p ${PORT:-3000}"]

FROM node:22-slim

WORKDIR /app

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
# Pin pnpm so the builder's supply-chain policy (release-age cooldown, build-script
# approval) behaves the same as the committed lockfile was resolved against.
RUN corepack enable && corepack prepare pnpm@11.18.0 --activate

# pnpm-workspace.yaml carries the approved-build settings (sharp, unrs-resolver);
# it must be present before install or pnpm 11 aborts on unapproved build scripts.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# Next.js resolves rewrite destinations at build time, so the backend URL the
# `/api/*` proxy points at must be known here — not just at runtime. Railway
# passes service variables to the Docker build, so set API_PROXY_TARGET as a
# service variable (e.g. https://your-backend.up.railway.app) before deploying.
ARG API_PROXY_TARGET
ENV API_PROXY_TARGET=${API_PROXY_TARGET}

ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

EXPOSE 3000

# Bind to the platform-assigned $PORT (falls back to 3000 locally).
CMD ["sh", "-c", "pnpm start -p ${PORT:-3000}"]

#!/usr/bin/env bash
# =============================================================================
# deploy-to-railway.sh — provision Silk United on Railway
#
# Silk United is a monorepo, not a single app. One GitHub repo produces FOUR
# services that share one Postgres and one Redis:
#
#   ┌─────────┐   ┌──────────┐   ┌────────┐   ┌────────┐
#   │  api    │   │  worker  │   │  beat  │   │  web   │
#   │ apps/api│   │ apps/api │   │apps/api│   │apps/web│
#   └────┬────┘   └────┬─────┘   └───┬────┘   └───┬────┘
#        └─────────────┴──── Postgres · Redis ────┴────┘
#
# `api`, `worker`, and `beat` build from the SAME Dockerfile (apps/api) with
# different start commands, selected by three config files:
#
#   service   root dir    config-as-code path        start command
#   ───────   ─────────   ────────────────────────   ─────────────────────
#   api       apps/api    railway.json               scripts/start-api.sh
#   worker    apps/api    railway.worker.json        scripts/start-worker.sh
#   beat      apps/api    railway.beat.json          scripts/start-beat.sh
#   web       apps/web    railway.json               pnpm start
#
# This script automates everything the Railway CLI can do headlessly:
#   • install the CLI, authenticate, create/link a project
#   • provision Postgres + Redis
#   • create the four GitHub-linked services with their shared variables
#     (wired as Railway reference variables, so secrets stay in one place)
#
# Two settings CANNOT be set through the current CLI (`railway add` has no
# --root-directory / --config flag) and MUST be finished in the dashboard:
#   • each service's Root Directory  (apps/api or apps/web)
#   • the worker/beat Config-as-code path (railway.worker.json / .beat.json)
# The script prints the exact values to paste when it is done — see
# docs/DEPLOY_RAILWAY.md for the full runbook.
#
# Usage:
#   ./deploy-to-railway.sh [--repo owner/repo] [--branch main]
#                          [--project-name silk-united] [--yes] [--dry-run]
#
#   --repo          GitHub repo to deploy (default: origin remote of this clone)
#   --branch        branch Railway auto-deploys from (default: origin's HEAD, else main)
#   --project-name  Railway project name to create (default: silk-united)
#   --link          link to the CURRENT Railway project instead of creating one
#   --yes, -y       non-interactive: never prompt (also skips confirmations)
#   --dry-run       print the Railway commands without running them
#   --help, -h      show this help
#
# Non-interactive auth (CI): export RAILWAY_TOKEN (project token) or
# RAILWAY_API_TOKEN (account token) and the script skips `railway login`.
# =============================================================================
set -euo pipefail

# ---- defaults ---------------------------------------------------------------
REPO=""
BRANCH=""
PROJECT_NAME="silk-united"
ASSUME_YES=0
DRY_RUN=0
LINK_EXISTING=0

# ---- pretty output ----------------------------------------------------------
if [ -t 1 ]; then
  BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); RESET=$(printf '\033[0m')
  GREEN=$(printf '\033[32m'); YELLOW=$(printf '\033[33m'); RED=$(printf '\033[31m')
else
  BOLD=""; DIM=""; RESET=""; GREEN=""; YELLOW=""; RED=""
fi
say()  { printf '%s\n' "$*"; }
info() { printf '%s→%s %s\n' "$DIM" "$RESET" "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%s✗ %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }
step() { printf '\n%s%s%s\n' "$BOLD" "$*" "$RESET"; }

usage() { sed -n '2,55p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

# ---- arg parsing ------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --repo)         REPO="${2:-}"; shift 2 ;;
    --repo=*)       REPO="${1#*=}"; shift ;;
    --branch)       BRANCH="${2:-}"; shift 2 ;;
    --branch=*)     BRANCH="${1#*=}"; shift ;;
    --project-name) PROJECT_NAME="${2:-}"; shift 2 ;;
    --project-name=*) PROJECT_NAME="${1#*=}"; shift ;;
    --link)         LINK_EXISTING=1; shift ;;
    -y|--yes)       ASSUME_YES=1; shift ;;
    --dry-run)      DRY_RUN=1; shift ;;
    -h|--help)      usage ;;
    # Bare positional arg is treated as owner/repo (compat with the old script).
    -*)             die "Unknown option: $1 (try --help)" ;;
    *)              [ -z "$REPO" ] && REPO="$1" && shift || die "Unexpected arg: $1" ;;
  esac
done

# ---- run a railway command (honours --dry-run) ------------------------------
# Reference values contain ${{Service.VAR}} which must survive verbatim, so the
# whole command is echoed with quoting but never re-evaluated by the shell.
rw() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '%s  [dry-run]%s railway' "$DIM" "$RESET"; printf ' %q' "$@"; printf '\n'
    return 0
  fi
  railway "$@"
}

# Tolerant variant: provisioning steps that may already exist should warn, not
# abort the whole run (keeps the script safe to re-run).
rw_soft() {
  if rw "$@"; then return 0; fi
  warn "railway $1 … did not succeed (already exists, or needs a dashboard step) — continuing"
  return 0
}

confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  [ -t 0 ] || return 0   # no TTY (CI without --yes): don't block
  printf '%s [y/N] ' "$1"
  read -r reply || true
  case "$reply" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

# ---- 0) banner --------------------------------------------------------------
step "🚂 Silk United → Railway"
[ "$DRY_RUN" = 1 ] && warn "dry-run: no changes will be made"

# ---- 1) Railway CLI ---------------------------------------------------------
step "1 · Railway CLI"
if command -v railway >/dev/null 2>&1; then
  ok "railway CLI present ($(railway --version 2>/dev/null || echo '?'))"
else
  info "installing Railway CLI…"
  if [ "$DRY_RUN" = 1 ]; then
    say "  [dry-run] bash <(curl -fsSL https://railway.com/install.sh)"
  else
    bash <(curl -fsSL https://railway.com/install.sh)
    export PATH="$HOME/.railway/bin:$PATH"
  fi
  command -v railway >/dev/null 2>&1 || [ "$DRY_RUN" = 1 ] \
    || die "railway CLI still not on PATH — add \$HOME/.railway/bin to PATH and re-run"
fi

# ---- 2) authenticate --------------------------------------------------------
step "2 · Authenticate"
if [ -n "${RAILWAY_TOKEN:-}" ] || [ -n "${RAILWAY_API_TOKEN:-}" ]; then
  ok "using token from environment (RAILWAY_TOKEN/RAILWAY_API_TOKEN) — skipping login"
elif [ "$DRY_RUN" = 1 ]; then
  info "would run: railway login"
elif railway whoami >/dev/null 2>&1; then
  ok "already logged in as $(railway whoami 2>/dev/null || echo '?')"
else
  info "opening a browser to log in… (headless? export RAILWAY_TOKEN instead)"
  railway login
fi

# ---- 3) resolve repo + branch ----------------------------------------------
step "3 · GitHub repo"
# Derive owner/repo from the origin remote when not supplied.
if [ -z "$REPO" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  origin_url=$(git remote get-url origin 2>/dev/null || echo "")
  # Normalise git@host:owner/repo.git and scheme://host[/extra]/owner/repo.git,
  # then keep only the final two path segments (owner/repo).
  REPO=$(printf '%s' "$origin_url" \
    | sed -E 's#\.git$##; s#^git@[^:]+:##; s#^[a-zA-Z]+://[^/]+/##' \
    | awk -F/ 'NF>=2{print $(NF-1)"/"$NF}')
fi
if [ -z "$REPO" ]; then
  [ -t 0 ] && { printf '📁 Enter the GitHub repo (owner/repo): '; read -r REPO || true; }
fi
[ -z "$REPO" ] && die "No repo specified (use --repo owner/repo)."
case "$REPO" in */*) : ;; *) die "Repo must be in owner/repo form (got: $REPO)" ;; esac

if [ -z "$BRANCH" ]; then
  BRANCH=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)
  [ -z "$BRANCH" ] && BRANCH="main"
fi
ok "repo   : $REPO"
ok "branch : $BRANCH"

# A SECRET_KEY shared by api/worker/beat/web (api signs tokens + derives the
# mailbox token-encryption key; web verifies the session JWT — it MUST be
# identical across all four).
gen_secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then python3 -c 'import secrets;print(secrets.token_hex(32))'
  # NEVER derive a signing/encryption key from time (epoch seconds are only a few
  # bits of entropy → forgeable session tokens and decryptable OAuth tokens). Fail
  # hard and make the operator supply a CSPRNG-generated key instead.
  else die "No CSPRNG available (need openssl or python3). Set SECRET_KEY yourself: openssl rand -hex 32"; fi
}
SECRET_KEY=$(gen_secret)

confirm "Create project ${BOLD}${PROJECT_NAME}${RESET} and deploy ${BOLD}${REPO}@${BRANCH}${RESET}?" \
  || die "Aborted."

# ---- 4) project -------------------------------------------------------------
step "4 · Railway project"
if [ "$LINK_EXISTING" = 1 ]; then
  info "linking to the current Railway project…"
  rw link
elif railway status >/dev/null 2>&1 && [ "$DRY_RUN" != 1 ]; then
  warn "a Railway project is already linked in this directory:"
  railway status 2>/dev/null || true
  confirm "Reuse this linked project (no new project created)?" \
    || die "Re-run with --link to reuse, or 'railway unlink' first to start clean."
  ok "reusing the linked project"
else
  info "creating project '$PROJECT_NAME'…"
  rw init --name "$PROJECT_NAME"
  ok "project created and linked"
fi

# Snapshot existing services once so re-runs skip what already exists.
EXISTING=""
if [ "$DRY_RUN" != 1 ]; then
  EXISTING=$(railway status --json 2>/dev/null || echo "")
fi
has_service() { printf '%s' "$EXISTING" | grep -q "\"name\"[[:space:]]*:[[:space:]]*\"$1\""; }

# ---- 5) databases -----------------------------------------------------------
# Postgres is provisioned from the pgvector image, NOT `--database postgres`:
# the api's very first migration runs `CREATE EXTENSION vector`, and Railway's
# stock Postgres has no pgvector — the api would crash-loop on first boot and
# login would never work. The image service exposes DATABASE_URL itself so the
# existing ${{Postgres.DATABASE_URL}} references keep resolving.
step "5 · Databases (Postgres w/ pgvector + Redis)"
if has_service "Postgres"; then ok "Postgres already present — skipping"
else
  info "adding Postgres (pgvector/pgvector:pg16 — required by the api's migrations)…"
  PG_PASSWORD=$(gen_secret)
  rw_soft add --service Postgres --image pgvector/pgvector:pg16 \
    --variables "POSTGRES_USER=silk" \
    --variables "POSTGRES_PASSWORD=${PG_PASSWORD}" \
    --variables "POSTGRES_DB=silk" \
    --variables "PGDATA=/var/lib/postgresql/data/pgdata" \
    --variables "DATABASE_URL=postgresql://silk:${PG_PASSWORD}@\${{RAILWAY_PRIVATE_DOMAIN}}:5432/silk"
  info "attaching a persistent volume to Postgres…"
  rw_soft volume add --service Postgres --mount-path /var/lib/postgresql/data
fi
if has_service "Redis"; then ok "Redis already present — skipping"
else info "adding Redis…"; rw_soft add --database redis; fi

# ---- 6) services ------------------------------------------------------------
# Shared backend variables. Reference variables (${{Service.VAR}}) are stored
# verbatim and resolved by Railway at deploy time:
#   • ${{Postgres.DATABASE_URL}} / ${{Redis.REDIS_URL}} — provisioned above.
#   • ${{api.RAILWAY_PUBLIC_DOMAIN}} — resolves once you generate a domain for
#     the api service (§7). API_BASE_URL/APP_BASE_URL/CORS stay correct after.
# STORAGE_BACKEND=local is ephemeral without a volume AND cannot serve product
# images across services: api and worker are separate containers, so a file://
# image the api writes is invisible to the worker's vision pass (it degrades to a
# text-only classification). For image classification to work, switch to
# STORAGE_BACKEND=s3 with real S3/R2/MinIO credentials and set
# REQUIRE_OBJECT_STORAGE=1 so a local misconfig fails loudly at startup.
# docs/DEPLOY_RAILWAY.md has the full object-store setup.
backend_vars() {
  cat <<EOF
ENVIRONMENT=production
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=\${{Postgres.DATABASE_URL}}
REDIS_URL=\${{Redis.REDIS_URL}}
API_BASE_URL=https://\${{api.RAILWAY_PUBLIC_DOMAIN}}
APP_BASE_URL=https://\${{web.RAILWAY_PUBLIC_DOMAIN}}
CORS_ORIGINS=https://\${{web.RAILWAY_PUBLIC_DOMAIN}}
STORAGE_BACKEND=local
COMTRADE_OFFLINE=1
EOF
}

# Create one GitHub-linked service and attach its variables.
#   $1 service name   $2..$N  KEY=VALUE variable pairs
add_service() {
  local name="$1"; shift
  if has_service "$name"; then ok "service '$name' already present — skipping"; return 0; fi
  info "creating service '$name' (linked to $REPO@$BRANCH)…"
  local kv; local -a varargs=()
  for kv in "$@"; do varargs+=(--variables "$kv"); done
  rw_soft add --service "$name" --repo "$REPO" --branch "$BRANCH" "${varargs[@]}"
}

step "6 · Services (api · worker · beat · web)"

# api — public HTTP, runs migrations + seed on boot (RUN_SEED handled by start-api.sh)
add_service "api"    $(backend_vars) "RUN_SEED=1"

# worker — Celery worker; same backend env, no public domain
add_service "worker" $(backend_vars)

# beat — Celery scheduler; needs the DB + Redis (and shares the same env for parity)
add_service "beat"   $(backend_vars)

# web — Next.js. API_PROXY_TARGET is read at BUILD time (Dockerfile ARG); Railway
# passes service variables into the build, so setting it here is enough.
# SECRET_KEY must be the SAME value the api signs tokens with: the Next.js server
# verifies the session JWT (verifyToken → SECRET_KEY); without it every logged-in
# page fails verification and bounces back to /login (login loop).
add_service "web" \
  "SECRET_KEY=${SECRET_KEY}" \
  "API_PROXY_TARGET=https://\${{api.RAILWAY_PUBLIC_DOMAIN}}" \
  "NODE_ENV=production"

# ---- 7) finish in the dashboard --------------------------------------------
step "7 · ✅ Provisioned — three quick steps left in the dashboard"
cat <<EOF
${DIM}The CLI can't set a service's Root Directory or Config-as-code path, so finish
these in the Railway dashboard (Project → each service → Settings):${RESET}

  ${BOLD}a) Root Directory & Config path${RESET}   (Settings → Source / Build)
        service   Root Directory   Config-as-code path
        ───────   ──────────────   ─────────────────────────────
        api       (repo root)      apps/api/railway.json
        worker    (repo root)      apps/api/railway.worker.json
        beat      (repo root)      apps/api/railway.beat.json
        web       apps/web         railway.json
     api/worker/beat build from the repo root (their Dockerfile needs the
     sibling packages/* in context) — leave Root Directory EMPTY for those.
     Then redeploy each service.

  ${BOLD}b) Public domains${RESET}   (Settings → Networking → Generate Domain)
     Generate one for ${BOLD}api${RESET} and one for ${BOLD}web${RESET}. Their
     API_BASE_URL / APP_BASE_URL / CORS / API_PROXY_TARGET reference variables
     resolve automatically once the domains exist. From the CLI you can also:
        railway service api && railway domain
        railway service web && railway domain

  ${BOLD}c) Secrets & persistence${RESET}   (each service → Variables / Volumes)
     • Real vendor keys (ANTHROPIC_API_KEY, SMARTLEAD_API_KEY, OAuth client
       ids/secrets, …) — all optional; blank keeps the deterministic mock.
     • STORAGE_BACKEND=local is wiped on redeploy. Attach a Volume at
       /app/storage on the ${BOLD}api${RESET} service (and worker, if it writes
       uploads), or set STORAGE_BACKEND=s3 with real S3/R2 credentials.
     • A SECRET_KEY was generated and set on api/worker/beat/web (identical
       across all four, as required — web verifies the session JWT). Rotate it
       in the dashboard for production.

Every push to ${BOLD}${REPO}@${BRANCH}${RESET} now auto-deploys all four services.
Full runbook: ${BOLD}docs/DEPLOY_RAILWAY.md${RESET}
Handy: ${DIM}railway status | railway logs | railway open${RESET}
EOF

# Deploying Silk United on Railway

Silk United is a **modular monolith deployed as four services** from this one
repository, sharing one Postgres and one Redis. Railway auto-deploys every push
to your production branch once the wiring below is in place.

```
        GitHub repo (this monorepo)
                    │
   ┌────────┬───────┴───────┬────────┐
   ▼        ▼               ▼        ▼
 ┌────┐  ┌──────┐        ┌────┐   ┌────┐
 │api │  │worker│        │beat│   │web │
 └─┬──┘  └──┬───┘        └─┬──┘   └─┬──┘
   │        │              │        │  Next.js → proxies /api/* to api
   └────────┴──── Postgres · Redis ─┘
```

`api`, `worker`, and `beat` build from the **same** image (`apps/api/Dockerfile`)
and differ only by start command, selected through three config-as-code files.
`web` is a separate Next.js image (`apps/web/Dockerfile`).

**Every service builds from the repo root** (leave Root Directory empty). Each
selects its Dockerfile with the `RAILWAY_DOCKERFILE_PATH` variable, and the three
backend services share one image, choosing their entrypoint with `SILK_ROLE`.

| Service  | Root Directory | `RAILWAY_DOCKERFILE_PATH` | `SILK_ROLE` | Public? |
|----------|----------------|--------------------------|-------------|---------|
| `api`    | _(repo root)_  | `apps/api/Dockerfile`    | `api`       | ✅ yes  |
| `worker` | _(repo root)_  | `apps/api/Dockerfile`    | `worker`    | no      |
| `beat`   | _(repo root)_  | `apps/api/Dockerfile`    | `beat`      | no      |
| `web`    | _(repo root)_  | `apps/web/Dockerfile`    | —           | ✅ yes  |

> **Why everything builds from the repo root.** `apps/api/pyproject.toml` depends
> on two editable path packages outside `apps/api` (`../../packages/silk_intel`,
> `../../packages/contracts`), so the api image's build context must include them.
> Building `web` from the root too lets *every* service leave Root Directory empty
> and pick its Dockerfile via `RAILWAY_DOCKERFILE_PATH` — which the CLI can set,
> so the whole deploy is headless (no dashboard clicks). The api image's `CMD`
> reads `SILK_ROLE` to run `scripts/start-<role>.sh`, so api/worker/beat need no
> per-service start command.
>
> The `apps/api/railway*.json` / `apps/web/railway.json` config files encode the
> same settings (`dockerfilePath` + an explicit `startCommand`) for anyone who
> prefers wiring services through a config-as-code path in the dashboard instead.

- **`api`** runs Alembic migrations and (by default) the idempotent seed on
  boot — migrations live only here, so schema changes apply exactly once per
  deploy (`apps/api/scripts/start-api.sh`).
- **`worker`** is the Celery worker (the market-intelligence engine runs
  in-process here — no HTTP hop).
- **`beat`** is the Celery scheduler (follow-ups, deliverability evaluation,
  daily counter resets, warm-up advancement).
- **`web`** proxies `/api/*` to `api`; its `API_PROXY_TARGET` is resolved at
  **build time**, so it must be set as a service variable before the build.

---

## Quick start

From a clean checkout:

```bash
./deploy-to-railway.sh                       # infers repo from your git remote
# or be explicit:
./deploy-to-railway.sh --repo owner/repo --branch main --project-name silk-united
```

The script (`deploy-to-railway.sh` at the repo root):

1. Installs the Railway CLI if missing.
2. Authenticates — browser login, or a token from the environment (see
   [Non-interactive / CI](#non-interactive--ci)).
3. Creates (or reuses) a Railway project.
4. Provisions **Postgres** (from the `pgvector/pgvector:pg16` image, with a
   persistent volume) and **Redis**.
   - **Why the image and not the bare Postgres plugin:** the first migration
     runs `CREATE EXTENSION IF NOT EXISTS vector` (product embeddings), and the
     stock Railway Postgres has no pgvector — the API would crash on boot with
     `type "vector" does not exist`. The script therefore creates the database
     service from the pgvector image and sets `DATABASE_URL` on it so the
     `${{Postgres.DATABASE_URL}}` references resolve unchanged. If you provision
     the database yourself instead, it MUST be pgvector-capable.
5. Creates the four GitHub-linked services with their shared variables wired as
   **reference variables** so secrets live in one place.
6. Prints the exact dashboard steps left to finish.

Useful flags: `--link` (reuse the currently linked project instead of creating
one), `--yes` (never prompt), `--dry-run` (print the Railway commands without
running them), `--help`.

> The script is safe to re-run: it skips databases and services that already
> exist (detected via `railway status --json`).

### One command, no dashboard (PowerShell)

On Windows, `deploy-to-railway.ps1` provisions **everything headlessly** — the
project, Postgres + Redis, all four services (Dockerfile + role selected via the
`RAILWAY_DOCKERFILE_PATH` / `SILK_ROLE` variables), and the api/web public domains:

```powershell
.\deploy-to-railway.ps1 owner/repo
```

Because every service builds from the repo root and picks its Dockerfile from a
variable, there is **nothing to set in the dashboard afterwards**. (The bash
script + the dashboard steps below remain available for the config-as-code path.)

---

## Finish in the dashboard (only for the config-as-code path)

`deploy-to-railway.ps1` needs none of this. It applies only if you wire services
through a **Config-as-code path** instead of `RAILWAY_DOCKERFILE_PATH`: the Railway
CLI has no flag for a service's **Root Directory** or **Config-as-code path**, so
those are set once per service in the dashboard.

### a) Root Directory & Config path

For each service: **Settings → Source** (Root Directory) and **Settings → Build**
(Config-as-code path), using the table at the top of this doc. Then **Redeploy**.

Leave **Root Directory empty** (repo root) for **every** service; all four
Dockerfiles build from the root. Set the config path per service:

- `api` / `worker` / `beat`: `apps/api/railway.json` (`.worker.json` / `.beat.json`).
- `web`: `apps/web/railway.json`.

A build that dies almost immediately with
`cannot normalize a relative path beyond the base directory: .../packages/...`
means a service still has a non-empty Root Directory; clear it.

### b) Public domains

For **`api`** and **`web`**: **Settings → Networking → Generate Domain**. This is
what makes the reference variables below resolve. From the CLI you can instead:

```bash
railway service api && railway domain
railway service web && railway domain
```

### c) Secrets & persistence

- **Vendor keys** (`ANTHROPIC_API_KEY`, `COMTRADE_API_KEY`, `SMARTLEAD_API_KEY`,
  the Google/Microsoft OAuth client ids/secrets, …) are all **optional** — a
  blank key keeps the deterministic mock adapter, so the product runs end to end
  with none of them. Add the real ones on `api` and `worker` when you're ready.
  See `.env.example` for the full annotated list.
- **File storage.** `STORAGE_BACKEND=local` writes uploads to the container
  filesystem, which Railway wipes on every redeploy. For persistence either
  attach a **Volume** at `/app/storage` on `api` (and on `worker` if it writes
  uploads), or set `STORAGE_BACKEND=s3` with real S3/R2 credentials
  (`S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`).
- **`SECRET_KEY`** is generated by the script and set **identically** on
  `api`/`worker`/`beat` (it signs auth tokens and derives the mailbox
  token-encryption key, so it must match across the three). Rotate it for
  production and, ideally, set an explicit `TOKEN_ENCRYPTION_KEY`
  (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).

---

## Environment variables

The script sets these; you rarely need to touch them by hand.

**Backend (`api`, `worker`, `beat`)**

| Variable         | Value set by the script                    | Notes |
|------------------|--------------------------------------------|-------|
| `ENVIRONMENT`    | `production`                               | |
| `SECRET_KEY`     | generated (same on all three)              | rotate for prod |
| `DATABASE_URL`   | `${{Postgres.DATABASE_URL}}`               | `postgres://…` is auto-rewritten to the psycopg driver in `app/config.py` |
| `REDIS_URL`      | `${{Redis.REDIS_URL}}`                     | Celery broker + cache |
| `API_BASE_URL`   | `https://${{api.RAILWAY_PUBLIC_DOMAIN}}`   | resolves after you generate the `api` domain |
| `APP_BASE_URL`   | `https://${{web.RAILWAY_PUBLIC_DOMAIN}}`   | resolves after you generate the `web` domain |
| `CORS_ORIGINS`   | `https://${{web.RAILWAY_PUBLIC_DOMAIN}}`   | |
| `STORAGE_BACKEND`| `local`                                    | see persistence note above |
| `COMTRADE_OFFLINE`| `1`                                       | serve trade data from committed fixtures |
| `RUN_SEED`       | `1` (`api` only)                           | set `0` once you have real data to preserve |

**Frontend (`web`)**

| Variable          | Value set by the script                  | Notes |
|-------------------|------------------------------------------|-------|
| `API_PROXY_TARGET`| `https://${{api.RAILWAY_PUBLIC_DOMAIN}}` | **build-time** — the `/api/*` proxy target is baked into the Next.js build |
| `NODE_ENV`        | `production`                             | |

Reference variables (`${{Service.VAR}}`) are stored verbatim and resolved by
Railway at deploy time. The two `RAILWAY_PUBLIC_DOMAIN` references only resolve
**after** you generate the corresponding domain (step **b**), so generate the
domains, then redeploy `api` and `web`.

---

## Verify

```bash
railway status                 # project + services
railway logs --service api     # boot: migrations → seed → uvicorn on $PORT
```

- `https://<api-domain>/health` → `{"status":"ok"}`
- `https://<web-domain>/` → the Arabic RTL app; sign in and run the golden path.

Then push a trivial commit to your production branch and confirm all four
services redeploy from GitHub automatically.

---

## Troubleshooting a crash-looping `api` service

`start-api.sh` validates configuration first, then runs migrations, and prints a
diagnosis matched to what actually failed. The three failures seen in practice:

- **`ValidationError: … TOKEN_ENCRYPTION_KEY is unset but ENVIRONMENT='production'`**
  (or the same for `SECRET_KEY`). The service is missing a required environment
  variable — the database is fine. This typically happens on services
  provisioned **before** the variable became mandatory: a re-run of
  `deploy-to-railway.sh` skips services that already exist, so the new variable
  is never added. Fix: generate a key
  (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
  and set `TOKEN_ENCRYPTION_KEY` to the **same value** on `api`, `worker`, and
  `beat` (each service → **Variables**), then redeploy. Rotating an existing
  key requires factories to reconnect their mailboxes.

- **`could not open extension control file … vector.control`** (or
  `type "vector" does not exist`). The database has no pgvector extension —
  the first migration runs `CREATE EXTENSION IF NOT EXISTS vector`, which a
  stock Postgres image fails. Fix: provision Postgres from the
  `pgvector/pgvector:pg16` image (the deploy script does this) and confirm
  `DATABASE_URL` points at it.

- **`connection refused` / `could not translate host name` / auth failures.**
  `DATABASE_URL` points at a database the service cannot reach. On Railway it
  should be the `${{Postgres.DATABASE_URL}}` reference variable; check the
  Postgres service is running and the reference resolves.

Anything else: the traceback in the deploy logs (`railway logs --service api`)
is the actual cause — read it before assuming a database problem.

---

## First login on production (read this before trying the demo accounts)

The demo accounts (`factory1@demo.silk` … `admin@demo.silk`; the password is
in `apps/api/app/seeds/seed.py`) exist **only** when `ENVIRONMENT=local` — on
production the seed deliberately skips them (C4: well-known passwords must
never exist on a public URL). So on a fresh deployment:

- **Factory users** sign up through the app's register page (`/ar/register`).
- **The first admin** is created from a shell **inside the running API
  container** — the public register flow never creates staff. Note that
  `railway shell`/`railway run` execute on your local machine (where the
  private `DATABASE_URL` does not resolve); use `railway ssh`, and `cd` first
  because Railway starts commands from the repo root:

  ```bash
  railway ssh --service api            # a shell inside the deployed container
  cd /app/apps/api
  python -m app.seeds.create_admin you@example.com --name "Owner"
  ```

  The command prompts for the new admin password (hidden — it is never
  printed, logged, or stored in plaintext); for non-interactive shells set
  `SILK_BOOTSTRAP_ADMIN_PASSWORD` instead. A new email is created as an active
  admin. An existing factory user is *promoted* to admin: the password you
  supply replaces their old one and their factory link is detached (previous
  role and factory are recorded in the audit log). A deactivated account is
  refused — reactivate it from the admin console instead. Re-running for an
  active admin is a no-op that writes nothing.

- **Known gap — staff created from the admin console.** Console-created staff
  get an unusable credential by design and gain access via the OTP/reset flow,
  but production has **no delivery channel for OTP codes** yet (codes are only
  surfaced in the HTTP response on `local` with `SILK_DEV_EXPOSE_OTP=1`; there
  is no transactional email sender). Until one is wired, create additional
  admins with the bootstrap command above, not the console.

---

## Non-interactive / CI

Export a token before running the script to skip the browser login:

```bash
export RAILWAY_TOKEN=...        # a project token (scoped to one project)
#   or
export RAILWAY_API_TOKEN=...    # an account/team token
./deploy-to-railway.sh --repo owner/repo --branch main --yes
```

With a token set and `--yes`, the script never prompts.

---

## Notes

- **Why four services and not one?** `worker`/`beat` are Celery processes with
  no HTTP surface, and `web` is a distinct Node image; only their start command
  (backend trio) or image (web) differs. Splitting them lets Railway scale and
  restart each independently while they share one Postgres and one Redis.
- **Local development** is unchanged and offline: `make dev` boots the whole
  stack (Postgres + Redis + MinIO + api + worker + beat + web) on deterministic
  mocks with zero API keys. This doc is only about the managed Railway deploy.
- **AWS alternative.** `infra/terraform/` sketches the intended production
  topology on AWS `me-south-1` (RDS + ElastiCache + S3 + ECS Fargate). It is an
  intentionally incomplete skeleton; Railway is the fast path.

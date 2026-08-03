---
name: railway-operations
description: Operating the live Railway deployment — one-container topology, volume/env routing, the security guard chain with paid keys active, redeploy consequences for async research runs, and the post-deploy health runbook. Load before deploying, changing env vars, or diagnosing anything that only happens in production.
---

# Railway operations — one container, one volume, real paid keys

Production reality (owner-confirmed): paid keys ARE active on Railway and the
system serves real clients. Treat every production action as spending someone's
money or trust.

## 1. Topology

- **One container** runs everything: uvicorn API + dashboard (static `web/`
  mounted at `/`), the in-process refresh scheduler, and SWR daemon threads.
  `Dockerfile` (python:3.11-slim) + `railway.json` (healthcheckPath `/health`,
  restart ON_FAILURE ×3, Railway injects `PORT`).
- **One volume** mounts at `/data`; `SILK_DATA_DIR=/data` routes all four stores
  (analyses `silk.db`, fact store `silk_store.db`, `usage.db`, `cache/`).
  Per-store vars (`SILK_DB`/`SILK_STORE_DB`/`SILK_USAGE_DB`/`SILK_CACHE_DIR`)
  win individually. **Never mount the volume over `data/`** — seed CSVs live
  there (`.env.example` warns explicitly).
- The scheduler stays in-process BY DECISION: a Railway volume mounts to exactly
  one service, so a separate cron service could not see `/data`
  (`silk_collectors.py` comment). Do not extract it.
- `netlify.toml` is an optional decoupled-frontend mode (static `web/` +
  `CORS_ORIGINS` on the backend); primary mode is same-origin.

## 2. The security guard chain (all run before any agent)

| Guard | Behavior | Anchor |
|---|---|---|
| `SILK_API_KEY` | missing/wrong `X-API-Key` ⇒ 401 (constant-time compare). MUST be set in prod — any paid provider key present without it ⇒ paid requests 503 + `/health` warning + free-path Claude extras blocked | `api.py:367` |
| `SILK_PAID_DAILY_CAP` | atomic reservation in `usage.db`; fail-closed; NEVER refunded; `/analyze` degrades, `/research` 409s, `/deepen` 429s | `silk_usage.py:118`, `api.py:427/481/504` |
| `CORS_ORIGINS` | default = middleware not installed (same-origin); `*` requires explicit opt-in | `api.py:61` |
| Rate limiter | in-memory fixed window per key/IP, default 120/60s (`SILK_RATE_LIMIT`/`SILK_RATE_WINDOW`); PER-PROCESS — resets on deploy, and becomes wrong the day anyone adds `--workers N` | `api.py:393` |
| `/diagnostics` | auth + rate-limited; fires LIVE probes with the server's keys; probe errors secret-redacted (`silk_diagnostics._redact`) | `api.py:1152` |

Key management: `POST /settings/keys` writes allow-listed SOURCE keys to store +
live `os.environ`; `SILK_API_KEY` is deliberately NOT in the allowlist (the panel
can never grant itself auth); deployment env beats panel keys at boot
(`load_settings_into_env(overwrite=False)`). Agent settings persist as one JSON
row outside the allowlist — the panel structurally cannot smuggle a key.

## 3. Redeploy consequences (the part that bites)

- **Daemon threads die.** An `async_run` /research mid-flight leaves DB status
  `running` forever — webhooks/watchdogs do NOT fix it. Recovery is manual:
  `POST /research` with `resume=<analysis_id>` re-runs only the missing missions
  (checkpoints in `research_missions`). Checkpoints make crashes RECOVERABLE,
  not self-healing.
- The in-memory rate limiter resets (harmless).
- The scheduler restarts and waits `SILK_REFRESH_INITIAL_S` (~120s) before its
  first run (`SILK_REFRESH_HOURS>0` enables it at all).
- Anything written outside `/data` is gone. If a result vanished after redeploy,
  suspect a literal path that bypassed the env-aware helpers (the PR #65
  hardcoded-`data/silk.db` incident).

## 4. Post-deploy runbook

1. `GET /health` → `status`, `deps`, `sources` (Claude shows "blocked" when its
   key is unprotected — that means SILK_API_KEY is missing!), `research_ready` +
   reason, **`storage` resolved paths** (verify all four point at `/data/...`),
   `warnings`.
2. Cheap smoke, no spend: `GET /markets`, `GET /resolve/tomato%20paste`.
3. Check for orphaned runs: `GET /analyses` for status `running` older than the
   deploy; resume or mark them.
4. Only if sources look broken: ONE call to `GET /diagnostics` (live probes).

## 5. Env-var quick reference (full docs in `.env.example`)

| Group | Vars |
|---|---|
| Auth/limits | `SILK_API_KEY`, `SILK_PAID_DAILY_CAP`, `SILK_RATE_LIMIT`, `SILK_RATE_WINDOW`, `CORS_ORIGINS` |
| Storage | `SILK_DATA_DIR` (+ per-store overrides), `SILK_TRACE_DIR` |
| Claude | `ANTHROPIC_API_KEY`, `SILK_AI_MODEL`, `SILK_AI_FAST_MODEL`, `SILK_AI_TIMEOUT_S` (60), `SILK_AI_LONG_TIMEOUT_S` (300) |
| Research budgets | `SILK_RESEARCH_MAX_LLM_CALLS` (40), `SILK_RESEARCH_MAX_TOOL_CALLS` (100), `SILK_MISSION_TOOL_CALLS` (5), `SILK_MISSION_TIMEOUT_S` (90) |
| Freshness/refresh | `SILK_FRESH_TRADE_DAYS` (90) / `_INDICATOR_` (30) / `_PRICE_` (7), `SILK_SWR`, `SILK_REFRESH_HOURS`, `SILK_REFRESH_INITIAL_S`, `SILK_REFRESH_BUDGET_RESERVE` (150), `COMTRADE_DAILY_BUDGET` (450 keyed / 4 keyless) |
| Behavior | `SILK_DYNAMIC_MARKETS`, `SILK_DECISION_WEIGHTS` (A/B), `SILK_HTTP_MIN_GAP_MS` (250) |

## 6. Known warts (documented, deliberate, or deferred — don't "discover" them)

- Daily-cap day bucket uses LOCAL date while store timestamps are UTC — harmless
  while the container TZ is UTC; remember it if TZ ever changes.
- `/trend` default `end_year` is hardcoded 2023 (Comtrade lag era) — reads like
  drift; fix computes-from-today if touched (see failure story #9).
- Cache filenames derive from url+params INCLUDING query-param API keys —
  rotating a key cold-starts that cache slice (values are not stored, only the
  filename hash is affected).
- Rate-limit state per-process; multi-worker deployment would need a rethink —
  but Redis is a settled "never" (change-rules §B).

# Repository Audit — Silk United (Export Intelligence + Outreach Platform)

**Date:** 2026-08-05 · **Type:** read-only `/audit` (no business logic changed) ·
**Follow-up to:** `CODE_AUDIT_2026-08-04.md`

Method: six parallel, read-only dimension passes (backend security · web security ·
architecture & API contracts · tests & CI/CD · infra/deploy/integrations · harness config).
Findings are anchored to `file:line`. No paid or production APIs were called; the only
commands executed were the offline hermetic test suite and the repo's own guard tools.
Secret *values* are never reproduced — variable names / locations only.

---

## 1. Executive summary

The security posture has improved **substantially** since 2026-08-04. **Both prior
CRITICALs and most prior HIGHs are fixed and, in several cases, locked by tests.** The
remaining risk has shifted from live-exploitable vulnerabilities to **release-process gaps**
and **architectural fragmentation**:

- **Login is broken out-of-the-box**: the web tier never receives `SECRET_KEY` in any run
  config, so it can't verify the session it just minted and bounces every logged-in user back to
  `/login` (login loop). One-line config fix, but it makes the whole authenticated app unreachable
  as shipped (Finding H-0).
- The project's own release gate (real-server + browser + PDF export, "rungs 2–3") **runs
  in no GitHub-triggered CI** — the workflows that would run it sit in a vendored path
  GitHub Actions never reads. Green CI does *not* prove the money/export path. (Prior
  CRITICAL-3 — still open.)
- Three separate backends (`silk_intel` engine, `silk_intel/silk_platform`, and `apps/api`)
  **reimplement the same analysis/ranking/report and cold-send logic**, so fixes on one
  path don't propagate and compliance rules diverge.
- Deploy/runtime hardening gaps persist: **containers run as root**, the **Railway deploy
  still provisions a non-pgvector Postgres** (boot crash-loop), and the **Smartlead
  cold-send path is unproven** with an unverified one-click-unsubscribe wiring.

None of the remaining items is a confirmed unauthenticated data breach on a correctly
configured deployment. The highest-leverage single fix is **wiring the rung-2/3 +
PDF-acceptance suite into root CI** — it closes the top finding and would have caught
several of the prior audit's shipped bugs.

### Severity totals (this audit, deduplicated)

| Severity | Count | Theme |
|---|---|---|
| Critical | 1 | release-gate suites unwired in CI |
| High | 7 | **login loop (web missing `SECRET_KEY`)** · root containers · pgvector deploy · Smartlead cold-send · missing invariant tests · 3-backend duplication · unauth readiness + rate-limit bypass |
| Medium | 11 | diagnostics paid-drain · CSP unsafe-inline · shared/weak secret default · login throttle · audit-log immutability · pagination limits · ephemeral storage · dockerignore · unpinned images · CI soft-skip/lint · token-in-body |
| Low | ~16 | proxy IP · os.environ key write · key derivation · realpath · sleeps · unpinned dev deps · doc drift · telemetry blob · terraform skeleton · healthchecks · etc. |
| Info | 3 | advisory-only root harness · keyless-agent URL notes · sample date churn |

---

## 2. Status of the 2026-08-04 audit items

| Prior item | Status | Evidence |
|---|---|---|
| CRITICAL-1 — OTP code in response body | **FIXED (+tested)** | `dev_code` gated to local+flag; `apps/api/tests/test_otp_hardening.py:24-46` |
| CRITICAL-2 — web token in JS-readable cookie | **FIXED** | httpOnly+SameSite+Secure(prod), `apps/web/src/app/api/session/login/route.ts:29-35` |
| CRITICAL-3 — rungs 2–3 / live-smoke never in CI | **OPEN** | see Finding C-1 |
| HIGH-1 — INCONCLUSIVE verdict export KeyError | **FIXED (+regression test)** | `silk_reports.py:720,737`; `tests/test_hs_gate_verdict_and_error_transparency.py:391-441` |
| HIGH-2 — research pools don't `copy_context()` | *not re-verified this pass* | (recommend targeted re-check) |
| HIGH-3 — no CSP/headers; unverified JWT; cookie no Secure | **FIXED** (CSP weak, see M-2) | `apps/web/next.config.ts:31-38`; `apps/web/src/lib/auth.ts:25-43` |
| HIGH-4 / HIGH-5 — LocalPrice / Maps key leak in notes/logs | **FIXED** | `silk_redact.redact_url()`; `silk_localprice_agent.py:131`, `silk_maps_agent.py:62-67` |
| HIGH-8 — per-tenant suppression (should be cross-tenant, I4) | **FIXED** | `silk_platform/email_queue.py:131-134` (match on email alone) |
| HIGH-9 — sent email can lose consent record + charge | **FIXED** | separate txns, `silk_platform/email_queue.py:216-264` |
| HIGH-10 — Smartlead cold-send unproven; one-click unsub | **OPEN** | see Finding H-3 |
| HIGH-11 — containers run as root | **OPEN** | see Finding H-1 |
| HIGH-12 — seed plants privileged admin w/ printed password | **FIXED** (engine analog) | `silk_platform/bootstrap.py:113-146` opt-in, random, no log; C4 handled in `apps/api` |
| HIGH-13 — Railway plain Postgres → pgvector crash | **PARTIAL** (diagnosable, still crashes) | see Finding H-2 |
| HIGH-14 — SECRET_KEY derived from epoch second | **FIXED** | `deploy-to-railway.sh:183-190` (CSPRNG, hard-fail) |
| HIGH-15 — I3/I4/I10 have no enforcing test | **OPEN** | see Finding H-4 |

---

## 3. Findings

### CRITICAL

#### C-1 — The release-gate suites (rungs 2–3, live-smoke, PDF-acceptance) run in no triggered CI
**Status:** prior CRITICAL-3, still open (refined). **Confidence:** confirmed (observed run + workflow trace).

- Root `.github/workflows/` contains exactly one file, `ci.yml`, with 6 jobs on push/PR.
  It sets **neither** `SILK_RUN_E2E` nor `SILK_RUN_LIVE` nor `SILK_PDF_ACCEPTANCE`
  (grep: none present), so the conftest gate (`packages/silk_intel/silk_intel/tests/conftest.py:157-170`)
  **skips** every rung-2/3, live, and PDF test.
- The only workflows that set those flags — `e2e-live-shape.yml:72` and `live-smoke.yml:23`
  — live under `packages/silk_intel/silk_intel/.github/workflows/`. **GitHub Actions only
  executes workflows in the repo-root `.github/workflows/`; nested `.github` paths are
  inert.** So the engine's own `ci.yml`, `e2e-live-shape.yml`, and `live-smoke.yml` never run.
- Observed in a real hermetic run: **2545 collected / 2524 passed / 0 failed / 21 skipped**;
  the 21 skips are 7× rung-2 + 6× rung-3 + 2× live-smoke + 6× PDF/soffice/font-gated.
- `packages/silk_intel/silk_intel/CLAUDE.md:47` still calls `e2e-live-shape` a "required CI
  job" and rungs 2–3 the release gate (`:36-50`). **That gate does not exist at the repo
  root**, so branch protection can't enforce it. Real-server boot, the browser export
  click-through, and docx/Markdown/PDF export ship green-untested.

**Impact:** export regressions (e.g. the prior HIGH-1 KeyError, RTL flips, tofu-glyphs) reach
the client deliverable with green CI; the "owner clicks once, expected-pass" promise rests
on tests that never executed.

**Fix:** add a root `.github/workflows/e2e-live-shape.yml` (node + chromium + LibreOffice +
fonts + pymupdf) that runs rungs 2–3 with `SILK_RUN_E2E=1` and the `SILK_PDF_ACCEPTANCE=1`
block; mark it a required check on `main`. Move `live-smoke.yml` to root (keep it
`workflow_dispatch`-only). This one change closes C-1 and H-5(H1).

*Note (refinement of prior prose):* root CI is **stronger** than 2026-08-04 described — it
does run the engine hermetic suite, the `apps/api` suite against a real `pgvector/pgvector:pg16`
Postgres + Redis with migrations, and a web build + mocked Playwright e2e. The load-bearing
gap is specifically the **real-server/browser/PDF** lane.

---

### HIGH

#### H-0 — Login is broken end-to-end: the web service never receives `SECRET_KEY`, so every post-login page bounces back to `/login` (login loop)
**Status:** new (functional blocker). **Confidence:** confirmed (traced across all three run configs).

The Next.js `verifyToken` fails closed on a missing secret — `apps/web/src/lib/auth.ts:30-31`
(`const secret = process.env.SECRET_KEY; if (!secret) return null;`) — and the authenticated
layouts redirect on a null result: `apps/web/src/app/[locale]/(app)/layout.tsx:14-17` and the
admin layout both `redirect("/login")` when `verifyToken` returns null. But **no run config gives
the web service `SECRET_KEY`**:

- `infra/docker-compose.dev.yml:99-100` — web `environment:` is only `API_PROXY_TARGET` (no
  `env_file`, unlike api/worker/beat at `:55,72,87`).
- `deploy-to-railway.sh:273-275` — web gets `API_PROXY_TARGET` + `NODE_ENV` only; `SECRET_KEY`
  is set on api/worker/beat only (`:181,263-269`).
- `deploy-to-railway.ps1:291-295` — web gets `API_PROXY_TARGET`/`NODE_ENV`/`RAILWAY_DOCKERFILE_PATH`
  only; `SECRET_KEY` is set on the backend services only (`:262`).

**Failure chain:** correct credentials → `/api/session/login` signs a valid token (apps/api) and
sets the httpOnly cookie → client redirects to `/dashboard` → `(app)/layout.tsx` calls
`verifyToken` → `process.env.SECRET_KEY` is undefined on the web server → returns null → redirect
to `/login`. The user submits valid credentials, sees no error, and lands back on the login page —
an infinite loop; the entire authenticated app is unreachable, in local `make dev` and on both
deploy scripts. (This is the functional face of the web review's M-3 shared-secret item, elevated
from hardening to a blocker because the web tier never receives the secret at all.)

**Fix:** set `SECRET_KEY` on the web service to the **identical** value used for api/worker/beat in
all three configs (api signs, web verifies, same HS256 secret). Optionally fail the web build/boot
loudly when `SECRET_KEY` is unset, so this can't recur silently.

#### H-1 — All container images run as root (prior HIGH-11, open)
`packages/silk_intel/silk_intel/Dockerfile` (no `USER`; also bundles LibreOffice + apt
toolchain that parses untrusted Arabic text via `soffice`), `apps/api/Dockerfile` (the image
Railway actually builds, `apps/api/railway.json:5` — no `USER`, runs celery/uvicorn as root),
`apps/web/Dockerfile` (no `USER`). A parsing RCE or compromised dependency runs as UID 0 with
write access to the mounted `/data` volume. **Fix:** add `useradd`+`chown`+`USER` before `CMD`
in all three; ensure the data dir is writable by that UID.

#### H-2 — Railway deploy provisions a non-pgvector Postgres → api crash-loops on first boot (prior HIGH-13, core open)
`deploy-to-railway.sh:222-223` runs `railway add --database postgres` (plain, no pgvector) with
no warning; `deploy-to-railway.ps1:243-249` warns but still provisions plain. The first
migration issues `CREATE EXTENSION IF NOT EXISTS vector` (`apps/api/alembic/versions/0001_initial.py:26`),
and `apps/api/railway.json` sets `restartPolicyType: ON_FAILURE, maxRetries: 10` → boot loop.
Mitigation since the audit: `apps/api/scripts/start-api.sh:9-18` now catches the Alembic
failure and prints a "provision a pgvector Postgres" message before `exit 1` (diagnosable, but
still fails out-of-the-box). Local dev is fine (`infra/docker-compose.dev.yml:12` uses
`pgvector/pgvector:pg16`). **Fix:** provision a pgvector-capable Postgres in both scripts.

#### H-3 — Smartlead cold-send activates on key presence, is UNPROVEN, and one-click unsubscribe depends on unverified console wiring (prior HIGH-10, open)
`apps/api/app/providers/registry.py:162-167` returns the live `SmartleadSendingProvider`
whenever `smartlead_api_key` is set — no live-smoke gate, no fail-closed "verified" flag.
`apps/api/app/providers/sending/smartlead.py:34-43` still reads "UNPROVEN pending live-smoke";
RFC-8058 `List-Unsubscribe`/`List-Unsubscribe-Post` are passed as lead `custom_fields`
(`:101-109`) via inline string literals, relying on a manually configured campaign template.
If the console step is missing or a field name mismatches, real cold email ships with no
working one-click unsubscribe (CAN-SPAM / I4/I8 exposure) and no proof the path works.
**Fix:** gate the live slot behind a passing live-smoke that asserts a received message
carries both headers; make field names shared constants; fail closed until verified.

#### H-4 — Money- and tenant-isolation invariants (I3 / I4 / I10) have no enforcing test (prior HIGH-15, confirmed)
- **Worker row-lock (I3):** `apps/api/app/services/sending.py:67` uses `.with_for_update()`,
  but there is no concurrency test (`grep threading|concurrent|with_for_update` in
  `apps/api/tests/` → none). Dropping the lock stays green.
- **Cross-tenant suppression (I4):** `apps/api/tests/test_suppression.py` covers only
  cross-*campaign* within a single factory fixture (`:66`); no two-factory test — the code
  fix (H-8 above) is unguarded against regression.
- **Locale parity (I10):** zero web unit tests (no vitest/jest, no `*.test.tsx`,
  `apps/web/package.json` has no test script; the `web` CI job runs no tests). Nothing asserts
  `messages/{ar,en}.json` key-set equality — an English-only regression ships green.

**Fix:** two-session `send_email` row-lock concurrency test; a two-factory suppression test; a
vitest key-parity test wired into a new `web` CI test step.

#### H-5 — Architectural fragmentation: three backends re-implement the analysis + cold-send spine
**Confidence:** confirmed. The frontend `apps/web` talks **only** to `apps/api` (Next rewrite
`/api/v1/* → FastAPI`, `apps/web/next.config.ts:45-51`). `apps/api` depends on the engine
(`pyproject.toml` editable `silk-intel`) but **reimplements** the spine as its own services —
`world_funnel.py`, `ranking.py`, `scoring.py`, `funnel_brief.py`, `report.py`, `report_view.py`
— while the engine (`api.py`) and `silk_platform/api.py` each drive their own vanilla-JS UIs.
Two **cold-send pipelines** coexist with divergent compliance: `apps/api` (Celery/Postgres,
3-layer I3 gate, global suppression) vs `silk_platform` (own `email_queue`, per-tenant
suppression semantics). HS-confirmation gates, ranking, brief/report generation, and role
vocabularies live in 2–3 codebases that can drift independently; the HIGH-1 verdict fix in the
engine does **not** propagate to `apps/api`'s report path. **Fix:** declare one canonical
analysis + send path and make the others thin adapters over `silk_render.build_view`; or
document the split and add contract tests pinning the shared shapes, and explicitly gate one
send pipeline off in prod.

**Master-Prompt conformance (base command vs UI).** `docs/MASTER_PROMPT.md` locks decision #2:
the engine (`packages/silk_intel`) is the ONE brain, *consumed* by the product via direct Python
imports. Reality is a partial match: `apps/api/app/services/engine.py` + `workers/tasks.py:76` do
consume the engine for **HS resolve/confirm** (I2) — but market **ranking, the 3-stage world
funnel, scoring, brief, and report are reimplemented** in `apps/api` (`world_funnel.py`,
`ranking.py`, `scoring.py`, `funnel_brief.py`, `report.py`, `report_view.py`) instead of deriving
from `silk_render.build_view`. So the engine's own `/analyze` base command (Repo A's ~38-market
ranker + `build_view` reports, with its vanilla-JS UIs `web/index.html`/`platform.html`, on SQLite)
and the shipped UI (the Master-Prompt 3-stage funnel over the `world_trade` table, on Postgres) are
**not the same intelligence** — they can and do diverge (e.g. the H (prior HIGH-1) INCONCLUSIVE
verdict fix landed in `silk_reports.py` but `apps/api/report.py` is a separate, un-inheriting path).
Net: the UI matches the Master Prompt's *product* Definition of Done, but decision #2's *one-brain*
intent is only partially honored, which is the concrete driver of this fragmentation risk. (The
SQLite-vs-Postgres split is intentional per decision #3; the ranking/funnel/report duplication is
not.)

#### H-6 — Unauthenticated `/research/readiness` drives live Comtrade calls, and the rate limiter is fully bypassable
**Confidence:** confirmed (two independent traces). `api.py:1941-1967` guards
`/research/readiness` with `_rate_limit` only (no `_require_key`); when
`SILK_WORLD_MARKETS`/`SILK_PRODUCER_ADVISORY`/`SILK_A2_PLAUSIBILITY` are enabled,
`_readiness_checks` (`api.py:1862-1898`) fires **live** `world_import_totals_resolved`,
`is_top_world_exporter`, and `supplier_plausibility` Comtrade queries before any auth. And the
rate-limit identity is attacker-controlled: `api.py:769-774` keys the limiter on the
`X-API-Key` *header value* (or client IP), so rotating the header mints a fresh bucket every
request — the throttle on all public routes (`/resolve`, `/config`, `/markets`, `/sources`,
`/index`, `/research/readiness`) is defeated. Result: anonymous Comtrade budget drain /
`(hs,iso3)` enumeration. **Fix:** add `_require_key` to readiness (and/or scope its live probes
under the Comtrade budget); on unauthenticated routes key the limiter on trusted client IP,
and use `X-API-Key` as a bucket key only *after* it matches.

---

### MEDIUM

#### M-1 — `/diagnostics` bypasses the 503 "unprotected paid keys" guard → anonymous paid-key drain in a plausible misconfig
`api.py:2618-2642` (see its own comment `:2626-2633`): unlike every other paid path,
`/diagnostics` intentionally skips `_guard_paid`'s 503, and its only spend guard is a cap
reservation that is itself conditional (`if silk_usage.daily_cap() is not None`, `:2636`).
`_require_key` is a no-op when `SILK_API_KEY` is unset. So a deployment with
`ANTHROPIC_API_KEY`/`GOOGLE_MAPS_API_KEY`/`SEARCH_API_KEY` set but `SILK_API_KEY` and
`SILK_PAID_DAILY_CAP` not yet set — the exact case the 503 guard exists for — lets an anonymous
caller drive live Serper/Maps/Anthropic calls and drain credit (throttle bypassable per H-6).
**Fix:** when any paid key is set and `SILK_API_KEY` is unset, require a cap (or apply the 503);
at minimum reserve 1 unit unconditionally when paid keys are present.

#### M-2 — CSP allows `'unsafe-inline'` for `script-src`
`apps/web/next.config.ts:17-29` (prod `script-src 'self' 'unsafe-inline'`). No active HTML sink
today (no `dangerouslySetInnerHTML` in `apps/web/src`), so this is defense-in-depth, but any
future XSS sink or vulnerable dep would execute. **Fix:** nonce/hash-based `script-src` (Next
supports a CSP nonce via middleware); drop `'unsafe-inline'`. The file's own comment already
flags this as follow-up.

#### M-3 — Token-signing secret has an insecure default that does not fail closed (API side)
`apps/api/app/config.py:21` defaults `secret_key = "dev-secret-key-not-for-production"`. The
web verifier fails closed on a missing secret (`apps/web/src/lib/auth.ts`), but the API signs
with the public default if `SECRET_KEY` is unset → anyone can forge `{"role":"admin","sub":…}`.
The web server now also holds the shared HS256 signing secret (blast radius). Overlaps prior
HIGH-14. **Fix:** hard-fail on the dev default when `environment != local`; document that web +
API share one high-entropy secret; consider RS256 so the web holds only a public key.

#### M-4 — Platform login throttle keyed on `email|ip` — no protection against spraying or distributed brute force
`silk_platform/throttle.py:34` / `silk_platform/api.py:288-297`. One IP trying one password
each against many emails never trips the per-pair counter; rotating IPs against one email also
never trips it. **Fix:** add aggregate limiters keyed on IP alone and on email alone (lockout),
in addition to the pair counter.

#### M-5 — Platform `audit_log` is freely UPDATE/DELETE-able (no append-only trigger)
`migrations/platform/001_platform_core.sql:90-102` creates `audit_log` with no
`RAISE(ABORT)` immutability triggers, whereas `ledger_entries` (`:132-137`) and
`consent_registry` (`:266-268`) have them. The record used to prove tenant-isolation breaches
(denials, admin funding, tier changes, logins) can be silently rewritten. **Fix:** add
`BEFORE UPDATE`/`BEFORE DELETE` `RAISE(ABORT)` triggers mirroring the ledger; revoke UPDATE/DELETE
from the app role.

#### M-6 — Platform pagination `limit` is unvalidated → `LIMIT -1` (unbounded) or memory sink
Passed straight to SQL in `list_funnels_ep` (`silk_platform/api.py:734,741`), `get_ledger_ep`
(`:1142,1149`), `factory_audit` (`:1156,1166`), `admin_audit` (`:1480,1485`). SQLite treats
`LIMIT -1` as unbounded. The clamp pattern already exists (`admin_list_accounts` uses
`_as_int(..., minimum=1, maximum=500)`, `:1498`) but is applied inconsistently. **Fix:** route
all four through `_as_int(..., minimum=1, maximum=N)`.

#### M-7 — Deploy scripts set `STORAGE_BACKEND=local` (ephemeral) → uploaded images wiped on every redeploy
`deploy-to-railway.sh:244`, `deploy-to-railway.ps1:268`; the `.ps1` then prints "Nothing left to
set in the dashboard" (`:303`), contradicting the need to attach a Volume. **Fix:** attach a
Railway Volume by default (or default to `STORAGE_BACKEND=s3` with real creds); remove the
"nothing left to set" claim.

#### M-8 — No `.dockerignore` for `apps/api` or `apps/web` (build context = repo root)
Only the engine has one. Both images build from repo root and `COPY apps/<x>/ ./`
(`infra/docker-compose.dev.yml:60-61,109-110`); any uncommitted local `.env`/`.env.local` on a
build host would be baked into a layer (plus bloated context). **Fix:** add `.dockerignore`
excluding `.env*`, `.git`, `node_modules`, `__pycache__`, `.venv`, `*.db`.

#### M-9 — Unpinned/floating base images + build-time font fetch from a mutable branch
`apps/api/Dockerfile:4` `ghcr.io/astral-sh/uv:latest` (worst), plus `python:3.11-slim` /
`node:22-slim` unpinned; engine `Dockerfile:18-20` `curl`s fonts from
`raw.githubusercontent.com/google/fonts/main/...` with no checksum. Non-reproducible builds /
supply-chain exposure. **Fix:** pin bases by `@sha256:` digest, pin `uv`, vendor the TTFs or
pin a commit SHA + `sha256sum -c`.

#### M-10 — CI soft-skips on missing deps + no engine lint/coverage floor
126 engine test files use `importorskip`; the root `silk_intel` job installs only
`requirements.txt pytest httpx` (no pymupdf/soffice/fonts), so 6 PDF/docx acceptance locks
**skip** in CI (observed) — a dropped requirements line silently turns a large surface into
green skips. The engine job is a bare `python -m pytest` (`.github/workflows/ci.yml:59`) with
no ruff and no coverage gate (only `apps/api` runs ruff). **Fix:** a collection-time hard-import
assertion in a CI lane (fail, don't skip, when a declared dep is missing); add ruff + a coverage
floor to the engine job.

#### M-11 — Platform login returns the raw session token in the JSON body in addition to the httpOnly cookie
`silk_platform/api.py:308-318` returns `{"token": raw, ...}` alongside the httpOnly cookie. Any
client that stores the body token in JS-readable storage forfeits the XSS protection the cookie
was added for, and it's more likely to land in logs/proxies. **Fix:** omit `token` from the body
for browser clients; return it only for explicit API/CLI consumers behind a flag.

---

### LOW

- **L-1 — No trusted-proxy `X-Forwarded-For` handling** (`api.py:774`, `silk_platform/api.py:108-109`):
  behind Railway/any proxy, all clients collapse to the proxy IP — anonymous rate-limit buckets
  merge (one abuser DoSes all) and audit/throttle forensics record the proxy. Parse XFF from a
  configured trusted hop only.
- **L-2 — `/settings/keys` writes provider keys into `os.environ`** (`api.py:1140-1159`): in
  open-dev mode any caller can shadow provider keys until reboot. Gate behind a dedicated owner
  key; persist without mutating the process env.
- **L-3 — One secret reused for Fernet key, HMAC keystream, MAC, and link signing** with only
  partial domain separation (`silk_platform/crypto.py:40-59`, `tokens.py:54-56`). Derive
  per-purpose subkeys via HKDF with distinct info labels.
- **L-4 — `serve_file` builds a path from the URL segment with no realpath-containment assert**
  (`silk_platform/storage.py:72-73`, consumed `api.py:1121`). Safe today only because the key is
  HMAC-signed + DB-row-checked; add a `realpath` under-`storage_dir()` assertion as
  defense-in-depth.
- **L-5 — `GET /analyses/{id}` returns the full operator telemetry blob** (`api.py:2740-2771`:
  `data_economics`, `llm_usage`, `mission_usage`, `trace_id`, raw `missions`) to any key holder
  — fully public in open-dev mode. Gate the heavy internal fields behind an `?economics` opt-in;
  never serve raw `missions` on the client path. (No secret leak observed; traces pre-scrubbed.)
- **L-6 — Platform write endpoints bypass pydantic** (`body: dict = Body(default=None)`, e.g.
  `silk_platform/api.py:284,476,503,935,1015`): validation is manual and generally thorough but a
  new field is easy to leave unvalidated and there's no OpenAPI contract. Consider typed models
  (the engine already uses them).
- **L-7 — ~10 engine tests use real wall-clock `time.sleep`** (e.g. `test_wave13_resilience.py`,
  `test_platform_concurrency.py`, `test_llm_provider_retry.py`): flake/slow risk (observed 221s
  single-threaded). Use fake/injectable clocks.
- **L-8 — CI dev tooling unpinned** (`ci.yml:55` `pytest httpx`; e2e `pymupdf`): observed
  `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated` — a future
  httpx major could break the `TestClient` transport ~all API tests use. Pin dev deps.
- **L-9 — `harness_verify.py` + the §58 self-review gate are not wired into root CI** (only the
  never-run vendored `ci.yml` calls the self-review gate). The harness contract the CLAUDE.md
  files assert does not execute. Wire both into root CI.
- **L-10 — Root `.env.example` omits engine provider keys the code reads**
  (`GOOGLE_MAPS_API_KEY`, `LOCALPRICE_API_KEY`, `SERPER_API_KEY`, `SEARCH_API_KEY`,
  `VOLZA_API_KEY`, `EXPLEE_API_KEY`); notably `serper_api_key` flips a live paid path in
  `apps/api` (`config.py:64`, `registry.py:81-84`). Document them (or point to the engine's own
  template).
- **L-11 — `deploy-to-railway.sh --dry-run` echoes the generated `SECRET_KEY`** (`:100-104,238`):
  the dry-run key is discarded, but it normalizes echoing signing-key material. Redact
  `SECRET_KEY`/key `--variables` in the dry-run printer.
- **L-12 — Terraform is a non-functional skeleton** (all `modules/*` are TODO stubs; `backend
  "s3"` commented at `main.tf:18`): no exploitable cloud vuln exists today, but it "reads as
  deployable" with no state backend, no public-access-block/SSE. Mark non-deployable; add a state
  backend + hardening before any `apply`; add `terraform validate`/`tflint`/`checkov` to CI.
- **L-13 — No `HEALTHCHECK` in app images; `apps/api/railway.json` has no `healthcheckPath`**:
  Railway can route traffic to a not-yet-ready api. Add `healthcheckPath: /health`.
- **L-14 — Smartlead/ZeroBounce pass the API key as a URL query param** (vendor-imposed,
  `smartlead.py:132`): can surface in proxy/APM logs. Scrub query strings from telemetry.
- **L-15 — Frontend `User.role` is a strict union; backend returns raw `str`** (`types.ts:8` vs
  `apps/api/app/schemas/auth.py:52`): a new backend role would be silently mistyped client-side.
  Tighten the backend to a Literal/enum.
- **L-16 — Committed sample reports embed the run date** (`samples/research_report_latest.md`
  header `| التاريخ |`): re-running the hermetic suite on any other day dirties the tree
  (observed: `2026-08-03 → 2026-08-05`). Freeze a fixed date in the sample fixture, or exclude
  the date line from the committed sample. Also, `packages/silk_intel/silk_intel/CLAUDE.md:106`
  ("CI runs exactly `pytest tests/ -q`… no linter config") is stale vs the real root CI.

---

### INFO / observations

- **Root harness is advisory-only.** Root `.claude/` has agents(4)+skills(3)+commands(3) but no
  `settings.json` → no hooks, no enforced permissions, no plugin. The real enforcement
  (`test_lessons_enforcement.py`, regression registry, AST guards, ponytail plugin) lives only at
  the package level. Nothing mechanically forces `/verify` or the security-review before
  `/finish`. If monorepo-level enforcement is wanted, add a root `.claude/settings.json` (hooks)
  or wire the Definition-of-Done checks into CI (see L-9).
- **Keyless agents interpolate raw exception URLs into customer-facing notes** (e.g.
  `silk_faostat_agent.py:128-132`, `silk_eurostat_agent.py:89-97`, `silk_gdelt_agent.py:78`):
  no secret leaks (these vendors take no key in the query), but route them through
  `silk_redact.redact_url()` for consistency with the C3 fix.

---

## 4. Positive controls verified (so the picture is balanced)

- **Single canonical view-model honored** in the engine: `/analyze` and `/research` attach
  `result["view"]`; `brief`/`report.docx`/`report.pdf`/`report.md` all call `build_view` fresh;
  one verdict entry point (`silk_synthesis.synthesize`) — no parallel `ai_verdict` path.
- **Paid/free boundary is structural**: `/analyze`/`/research` models carry no paid fields;
  `/deepen` is the only paid path, inside `deepen_context()` with `_guard_paid`.
- **Tenant isolation in the platform API is disciplined**: `account_id` always from session
  (never request), 404-not-403 existence hiding, SMTP creds stripped, reset token withheld in
  prod.
- **Atomic paid daily-cap reservation** (`BEGIN IMMEDIATE` check-and-reserve, fail-closed on DB
  error, `silk_usage.py:261-298`); parameterized SQL throughout; HMAC via `hmac.compare_digest`;
  `serve_file` double-guarded by HMAC signature + DB row.
- **`.gitignore` excludes all `.env*`, `*.db`/`*.sqlite`, tfstate/tfvars; no secrets or DBs are
  tracked. `.env.example` contains no real secrets** (placeholders + well-known local MinIO dev
  defaults; `CORS_ORIGINS` no wildcard).
- **Guards that DO run in CI**: pandas confinement (I7, `check_no_pandas.py`), the 142 KB
  regression registry, and the 48 KB lessons-enforcement suite are part of the 2524 passing
  hermetic tests; `apps/api` runs against a real `pgvector/pgvector:pg16` + Redis with migrations.

---

## 5. Recommended priority order

1. **C-1 / H-4 / M-10** — wire a root `e2e-live-shape.yml` (rungs 2–3 + PDF-acceptance, required
   check) and add the three missing invariant tests (I3 row-lock, I4 two-factory suppression,
   I10 locale parity). Highest leverage: restores the release gate the whole harness assumes.
2. **H-6 / M-1 / M-3** — close the unauth/misconfig paid-drain surface: `_require_key` on
   `/research/readiness`, IP-based limiter on public routes, unconditional cap when paid keys
   present, and fail-hard on the dev `secret_key` default outside local.
3. **H-1 / H-2 / H-3** — deploy hardening: non-root containers, provision pgvector Postgres,
   fail-closed Smartlead slot behind a passing live-smoke.
4. **H-5** — decide and document the one canonical analysis/send path; add contract tests; gate
   the redundant cold-send pipeline off in prod.
5. Medium/Low hardening (CSP nonce, audit-log triggers, pagination clamps, `.dockerignore`,
   pinned images, throttle aggregation) as follow-ups.

---

## 6. Coverage statement

Read-only audit — no business logic modified; no paid or production APIs called. The only
commands run were the offline hermetic engine suite (**2545 collected / 2524 passed / 0 failed /
21 skipped / 221.6s**, pytest 9.1.1 / Python 3.11.15), `tools/check_no_pandas.py` (OK), and
`tools/harness_verify.py` (OK). Findings come from six parallel targeted traces
(security/contracts/CI/infra/harness) anchored to `file:line`, plus verification of the
2026-08-04 items. A full line-by-line review of all 557 Python files and the full frontend was
not performed; areas explicitly *not* re-verified this pass are flagged inline (e.g. HIGH-2
`copy_context`). "Not found / not verified" is stated rather than assumed.

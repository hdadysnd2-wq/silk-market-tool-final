# Complete Code Audit — Silk United (Export Intelligence Platform)

**Date:** 2026-08-04 · **Auditor role:** Staff Software Engineer (read-only; no code modified)
**Scope:** entire monorepo — `packages/silk_intel` engine (71 modules + `silk_platform/` 28 modules + `tools/` 33), `apps/api` (FastAPI+Celery+SQLAlchemy+Alembic), `apps/web` (Next.js), `etl/`, `infra/`, `packages/contracts`, CI, Docker, deploy scripts, and the full test suite (259 files).

**Method:** 13 parallel Staff-Engineer readers, each reading its assigned files top-to-bottom, judged against the governing specs — MASTER_PROMPT invariants **I1–I10** and the engine change-rules **A1–A12** — plus direct review of the security-critical files (`config.py`, `crypto.py`, `security.py`, `main.py`, the pandas guard, CI). Every finding is anchored to a line the reader actually saw.

---

## Severity totals

| Severity | Count |
|---|---|
| CRITICAL | 3 |
| HIGH | 15 |
| MEDIUM | 48 |
| LOW | 60 |
| INFO / positive | 25 |

CRITICAL/HIGH are detailed in full below; MEDIUM/LOW are listed with severity, file:line, explanation, and fix, grouped by the nine requested categories. A finding that spans categories is filed under its dominant one and cross-referenced.

---

## The headline issues (CRITICAL + HIGH)

### CRITICAL-1 — OTP one-time code returned in the HTTP response body → pre-auth account takeover
- **Category:** Security / Production blocker
- **File:** `apps/api/app/api/auth.py:55-58`
- **Explanation:** `request_otp` returns `{"detail":"OTP issued","dev_code": code}` — the real OTP — unconditionally, with no `if settings.environment=="local"` guard. Anyone who knows a victim's email can `POST /auth/otp/request`, read `dev_code`, then `POST /auth/otp/verify` to mint a valid access token. Full account takeover for any OTP user. The existing `test_otp_flow` actually depends on the leak (`tests/test_auth.py:56-74`), and a second copy of the code is written to logs (`services/auth_service.py:88`).
- **Fix:** Gate `dev_code` behind an explicit dev flag (`environment=="local"`), deliver the code out-of-band otherwise, stop logging the plaintext code, and add a test asserting `dev_code` is absent when `environment!="local"`.

### CRITICAL-2 — Web auth token stored in a JS-readable cookie (comment claims httpOnly; it is not) → XSS = account takeover
- **Category:** Security
- **File:** `apps/web/src/lib/api.ts:1-3,15-19`; `app/[locale]/(auth)/login/page.tsx:27`; `register/page.tsx:35`
- **Explanation:** The header comment claims the JWT lives in an httpOnly cookie set by a route handler. There is no route handler — the client sets `document.cookie = "silk_token=…; samesite=lax"` and `readTokenFromCookie()` reads it back via `document.cookie`. A cookie set from JS cannot be httpOnly, so any XSS (or a malicious dependency) exfiltrates a valid 12-hour bearer token. The cookie also lacks `Secure` (HIGH-3), so it also transits plaintext HTTP.
- **Fix:** Set the cookie server-side (Route Handler / Server Action) with `HttpOnly; Secure; SameSite=Lax`; proxy authenticated calls through a same-origin server route; remove `readTokenFromCookie`; correct the comment.

### CRITICAL-3 — Rungs 2–3 + live-smoke test suites never run in any CI; "green CI" proves only the hermetic layer
- **Category:** Missing tests / Production blocker
- **File:** `packages/silk_intel/silk_intel/.github/workflows/e2e-live-shape.yml:72`, `.../live-smoke.yml:23` (a *vendored* `.github` path GitHub Actions never reads); gate at `tests/conftest.py:141-170`
- **Explanation:** The engine conftest gates `@pytest.mark.e2e`/`@pytest.mark.live` off unless `SILK_RUN_E2E=1`/`SILK_RUN_LIVE=1`. The only workflows that set those flags live under `packages/silk_intel/silk_intel/.github/workflows/` — GitHub only runs workflows in the repo-root `.github/workflows/`, which has just `ci.yml`, which sets neither flag. **15 test functions never execute** (`test_rung2_real_server.py` ×7, `test_rung3_playwright_e2e.py` ×6, `test_live_smoke.py` ×2). CLAUDE.md calls `e2e-live-shape` a "required CI job" and rungs 2–3 the release gate — but the gate is unwired at the monorepo root, so a regression in real-server boot, the Playwright export flow, or docx/markdown export ships green.
- **Fix:** Add a root `.github/workflows/e2e-live-shape.yml` that runs the rung-2/rung-3 suites with node+chromium; until then, stop describing rungs 2–3 as CI-enforced.

### HIGH-1 — INCONCLUSIVE verdict crashes every deep-research Word/PDF/client/academic export (unhandled KeyError)
- **Category:** Production blocker / Prompt-compliance robustness
- **File:** `packages/silk_intel/silk_intel/silk_reports.py:713-716,732` (`_add_verdict_badge`)
- **Explanation:** `_verdict_tone()` returns `"inconclusive"` for the routine `PRELIMINARY / INCONCLUSIVE` jury verdict (emitted whenever a mission/agent fails while real results remain; the committed `samples/analysis_latest.json` carries it). `_VERDICT_LABELS_AR` has the `"inconclusive"` key but `_VERDICT_TEXT_COLORS` does not, and line 732 indexes it directly (`rgb = _VERDICT_TEXT_COLORS[tone]`) with no try/except. Every deep-research exporter (`_render_research_docx`, `render_client_docx`, `render_academic_docx`) aborts with a KeyError — the same "report=None"-class delivery failure the repo has fought before. `preliminary` was added to the color map; `inconclusive` was missed.
- **Fix:** Add an `"inconclusive"` entry to `_VERDICT_TEXT_COLORS`, or use `_VERDICT_TEXT_COLORS.get(tone, (0x60,0x60,0x60))` (mirroring the safe `.get` on line 736). Add a regression test asserting `set(_VERDICT_TEXT_COLORS)==set(_VERDICT_LABELS_AR)` and a full docx render for an inconclusive verdict.

### HIGH-2 — Research thread pools don't `copy_context()` → AI-spend block, agent-disable panel, and operator steer all silently bypassed
- **Category:** Prompt-compliance (I5 / A4) / Security (spend)
- **File:** `packages/silk_intel/silk_intel/silk_research.py:1252-1253` (`ResearchOrchestrator.run_market`) and `silk_engine.py:455-456` (`_enrich_research`)
- **Explanation:** Both pools submit work without `contextvars.copy_context()`. Worker threads don't inherit contextvars, so inside every threaded `ResearchAgent`: `ai_extras_blocked()` reads its default `False` ⇒ `silk_ai_judge.available()` returns True and the Claude calls (`_qualify_entities`, `extract_companies`, `extract_prices`) **fire even when `api.py` entered `block_ai_extras()`** (Anthropic key present without `SILK_API_KEY`, or daily cap exhausted) — a spend-guard bypass; `agent_enabled(PREF_KEY)` reads default `True` ⇒ a user-disabled agent still runs; `agent_command` and `deepen_active` are also lost. The authors fixed the identical pattern in `silk_missions.py:557` (with a comment calling the un-copied case a "dangerous silent failure") but never applied it here.
- **Fix:** Submit through `contextvars.copy_context().run` in both functions (a distinct copy per task), and add a hermetic test running the orchestrator under `block_ai_extras()`/`agent_prefs_context({...:False})` asserting zero calls.

### HIGH-3 — Web: no CSP or any security headers; route-gate trusts an unverified JWT; cookie missing `Secure`
- **Category:** Security
- **File:** `apps/web/next.config.ts:6-13` (no `headers()`); `app/[locale]/(app)/layout.tsx:11-28` (`decodeRole` base64-decodes the JWT payload with **no signature check**, gate is cookie-presence only); `login/page.tsx:27` (no `Secure`)
- **Explanation:** The Next config emits no CSP, HSTS, X-Frame-Options, X-Content-Type-Options, or Referrer-Policy — so the app is clickjackable and the JS-readable token (CRITICAL-2) has no defense-in-depth. The `(app)` layout gates on cookie presence and derives `isAdmin` from an **unverified** JWT payload — an attacker forges `{"role":"admin"}`; expired tokens still pass; the API client never handles 401→login. `fixtures.ts:16` openly confirms "no signature check." The `/admin` route itself is not role-gated server-side (only the nav link is hidden — `admin/page.tsx:23-51`), so any authenticated user can open it and fire `/admin/suppression` + `/admin/audit`.
- **Fix:** Add a strict `headers()` block (CSP `default-src 'self'`, `frame-ancestors 'none'`, HSTS, nosniff, Referrer-Policy). Verify the JWT server-side (or call `/me`) before trusting `role`; on 401 clear cookie + redirect. Gate the `/admin` segment server-side. Add `Secure` to the cookie.

### HIGH-4 — LocalPrice (paid) API key leaks into failure notes and logs via the URL query string
- **Category:** Security
- **File:** `packages/silk_intel/silk_intel/silk_localprice_agent.py:118,122,126-128`
- **Explanation:** The SerpApi key is placed in the URL query string (`params={"api_key": key}`) and sent with `requests.get`. On any HTTP/Connection error, `requests` builds a message embedding the full URL incl. `&api_key=<SECRET>`; that exception is logged verbatim (`log.warning(...%s, e)`) **and** interpolated into a customer-facing DataPoint note (`f"local price fetch failed: {e}"`), which is stored in the deepen result and can be rendered. No sanitizer redacts arbitrary keys; no test guards it.
- **Fix:** Send the key in a header (mirror `silk_wto_tariff.py:119-122`); if the vendor requires a query param, never interpolate raw `e` — log `type(e).__name__` + a redacted URL. Add a regression test asserting the key never appears in note or logs.

### HIGH-5 — Google Maps (free-path, customer-visible) API key leaks into notes and logs the same way
- **Category:** Security
- **File:** `packages/silk_intel/silk_intel/silk_maps_agent.py:49,53,57,64-65`
- **Explanation:** Same class as HIGH-4 and worse: `MapsAgent` is `PAID=False`, so its findings flow through the free `/analyze` path into customer reports. On a network error the exception embeds `…&key=<SECRET>` and is logged and interpolated into `f"Google Maps fetch failed: {e}"` — a live Google Maps key can print in a client deliverable.
- **Fix:** Redact the URL and note only `type(e).__name__`; never interpolate the raw exception into a stored/rendered note. Add a regression test.

### HIGH-6 — I9 transit-port guard is absent from the ranking path (no re-export-hub tag, no score penalty)
- **Category:** Prompt-compliance (I9)
- **File:** `packages/silk_intel/silk_intel/silk_market_ranker.py:682-794` (scoring body), `394-400` (`WEIGHTS`)
- **Explanation:** I9 mandates that re-export hubs (AE, NL, SG, HK, BE) be tagged AND score-penalized. The ranker has no hub set, no penalty term, no tag on the row dict. NLD/ARE/SGP/BEL are in `COUNTRIES` and in the "top world importers" candidate list — they are large importers *because they re-export*. With `market_size` weighted 0.40 and min-max normalized, a hub often maxes it and surfaces as a top market for a Saudi exporter with zero warning — exactly what I9 exists to prevent. (The mirror-tagging half of I9 *is* satisfied, which masks the gap.)
- **Fix:** Add a data-driven hub set (from `data/market_profiles.json`), apply a `transit_hub` tag + a bounded score penalty, and add a lock test asserting a hub ranks below an equivalent non-hub.

### HIGH-7 — SWR background refresh spawns unbounded daemon threads whose live Comtrade calls escape the daily budget
- **Category:** Performance / Production blocker
- **File:** `packages/silk_intel/silk_intel/silk_data_layer_v2.py:304-312,358-362`
- **Explanation:** Every stale store hit fires `threading.Thread(...).start()` with no pool, cap, or de-dup. `rank_markets` fans over up to 38 markets; a warm-but-stale store can spawn ~38 daemon threads each calling `comtrade_trade` live. Those calls are **not** counted against `COMTRADE_DAILY_BUDGET` (the ledger only sums `collection_runs` rows written by the collectors), so the budget gate in `rank_markets` can't see SWR spend and the reserve it "protects" can be blown by the threads it spawned — uncounted, unbounded fan-out that trips 429s and exhausts the free quota. Only `SILK_SWR=0` mitigates.
- **Fix:** Route SWR through a bounded, de-duplicated queue and count live/SWR Comtrade calls against the same daily budget as the collectors.

### HIGH-8 — Suppression is per-tenant in the `silk_platform` pipeline, violating cross-tenant suppression (I4)
- **Category:** Prompt-compliance (I4) / Security (compliance)
- **File:** `packages/silk_intel/silk_intel/silk_platform/email_queue.py:126-130,167`; `silk_platform/api.py:431-434`; `migrations/platform/001_platform_core.sql:270-278`
- **Explanation:** In the platform pipeline `suppression_list` is `UNIQUE(account_id, email)`, unsubscribe inserts with the sending `account_id` only, and `_suppressed()` filters `WHERE account_id=? AND email=?`. A prospect who unsubscribes from Factory A's cold email is suppressed only for Factory A; Factory B can still send to them — the CAN-SPAM/PDPL exposure the cross-tenant rule prevents. (Note: the parallel `apps/api` pipeline **does** check suppression globally with no tenant filter — `services/sending.py:113` — so this defect is specific to the `silk_platform` send path.)
- **Fix:** Add a platform-global suppression check at send time (global list keyed on `email`, or an `OR` clause matching any tenant); have unsubscribe record a global suppression. If per-tenant is intended, amend the I4 invariant text.

### HIGH-9 — A physically-sent platform email can lose both its append-only consent record and its charge
- **Category:** Prompt-compliance (I4 append-only consent) / money leak
- **File:** `packages/silk_intel/silk_intel/silk_platform/email_queue.py:222-252` (except at 245-252)
- **Explanation:** In `process_queue`, `sender(...)` physically transmits at line 204; only afterward, inside `BEGIN IMMEDIATE`, does it insert the `consent_registry` record, post the ledger debit, and set `status='sent'`. If any statement in that block raises (lock timeout, disk-full, overdraft), the `except` rolls back the whole block — discarding the consent record for a message that already left — and marks the row `failed`. Result: a cold email was sent with **no append-only consent/audit record** (I4 breach) and **no charge** (money leak); because the row ends `failed`, `reap_stuck` never retries, so the loss is silent and permanent. The docstring asserts the consent record is "never rolled back"; the code does exactly that on error.
- **Fix:** Commit the consent/verbatim record in its own transaction the instant `sender()` returns; book the debit separately; on debit failure record declared arrears rather than discarding the send record.

### HIGH-10 — Smartlead cold-send path is UNPROVEN and one-click unsubscribe depends on unverified console wiring
- **Category:** Production blocker / Prompt-compliance (I4/I6/I8/CAN-SPAM)
- **File:** `apps/api/app/providers/sending/smartlead.py:34-43,95-127`
- **Explanation:** The adapter's own docstring marks the path "UNPROVEN pending live-smoke (PR #40)." The RFC-8058 `List-Unsubscribe`/`List-Unsubscribe-Post` headers are **not** emitted by the call — they are passed as lead `custom_fields` and rely on a Smartlead campaign template being manually configured to emit those exact headers from those exact field names. If that console step is missing or names mismatch, real cold email ships with no working one-click unsubscribe — a direct I4/I8/CAN-SPAM violation. This is the live cold-send route.
- **Fix:** Gate the live Smartlead slot behind a passing live-smoke that asserts a received message carries both headers; make the custom-field names shared code constants; fail closed until verified.

### HIGH-11 — Docker image runs the FastAPI app as root (engine image also bundles LibreOffice parsing untrusted text)
- **Category:** Security / Production blocker
- **File:** `packages/silk_intel/silk_intel/Dockerfile:1-34` (no `USER`); also `apps/api/Dockerfile:44-52` and `apps/web/Dockerfile:31-36` (MEDIUM — both run as UID 0)
- **Explanation:** No image drops privileges. The engine image embeds LibreOffice + a full apt toolchain and runs untrusted-shaped Arabic text through `soffice` for PDF conversion; a parsing RCE or dependency compromise lands as root inside the container, able to write the mounted Railway `/data` volume (the only persistent store).
- **Fix:** Add a non-root user (`useradd`, `chown`, `USER`) before `CMD` in all three images; ensure `/data` is writable by that UID.

### HIGH-12 — Seed plants a privileged admin with a hardcoded, printed password and no prod guard
- **Category:** Security / Production blocker
- **File:** `apps/api/app/seeds/seed.py:33,105-155,301-303`
- **Explanation:** `seed.py` creates `admin@demo.silk` (admin), `analyst@demo.silk`, and six factory users all with `"Demo1234!"` and prints it. `run()` has no `environment!="production"` guard, so a deploy/entrypoint hook or an accidental run against a shared/prod DB plants a privileged admin with a publicly-known credential — full auth bypass on a platform sending real cold email and holding tenant PII. (The related `demo_golden_path.py:100,122` labels its send "mock provider" but calls `get_sending_provider()`, which picks the REAL adapter if a key is set — an accidental paid-send leak.)
- **Fix:** Refuse to seed without an explicit non-prod flag; generate a random password (or require one via env); never print a static one; force the golden-path demo to construct mock providers explicitly.

### HIGH-13 — Railway deploy scripts provision plain Postgres → api crash-loops on `CREATE EXTENSION vector`
- **Category:** Production blocker
- **File:** `deploy-to-railway.sh:217-222`; `deploy-to-railway.ps1:243-252`
- **Explanation:** The api boots by running Alembic to head, which issues `CREATE EXTENSION vector` (pgvector). Both scripts provision Railway's plain Postgres plugin, which lacks pgvector, so the api crash-loops with `type "vector" does not exist`. This is the documented primary deploy path; the `.sh` gives no warning at all.
- **Fix:** Provision a pgvector-capable Postgres (Railway pgvector template or a `pgvector/pgvector` image) and point `DATABASE_URL` at it; fail loudly if the `vector` extension is absent.

### HIGH-14 — `deploy-to-railway.sh` SECRET_KEY fallback derives the signing/encryption key from the epoch second
- **Category:** Security
- **File:** `deploy-to-railway.sh:183-188` (`gen_secret`)
- **Explanation:** `SECRET_KEY` signs auth tokens and derives the Fernet key that encrypts mailbox OAuth tokens at rest. When neither `openssl` nor `python3` is present, the key becomes `sha256(<deploy-epoch-second>)` — a few seconds of entropy, brute-forceable offline → forgeable session tokens and decryptable OAuth tokens. The ultimate fallback `change-me-<timestamp>` is worse. (The PowerShell script correctly uses a CSPRNG.)
- **Fix:** Fail hard when no CSPRNG is available; never fall back to time-based key material.

### HIGH-15 — I3 worker row-lock, I4 cross-tenant suppression, and I10 locale-parity have no enforcing test
- **Category:** Missing tests
- **File:** `apps/api/app/services/sending.py:67` (`with_for_update()`, untested); `apps/api/tests/test_suppression.py:66` (cross-*campaign* only, not cross-tenant); `apps/web/messages/{ar,en}.json` (no parity test; `web` CI runs no unit tests)
- **Explanation:** The 3-layer send gate's API and DB-CHECK layers are tested, but the worker `SELECT..FOR UPDATE` row-lock — the layer preventing concurrent double-send — has no concurrency test; a refactor dropping `.with_for_update()` keeps every test green. Cross-tenant suppression (I4) is proven only within one factory. The 236-key ar/en catalogs have nothing asserting key-set equality, and there are no web unit tests at all, so an English-only regression (e.g. the hardcoded admin tabs) ships green.
- **Fix:** Add a two-session concurrency test on `send_email`; a two-factory suppression test; a vitest asserting recursive `Object.keys(ar)` deep-equals `en`, wired into the `web` CI job.

---

## 1. Architecture issues

- **MEDIUM — Two parallel campaign/send pipelines with divergent compliance guarantees.** `apps/api` (Celery, Postgres, the canonical 3-layer I3 gate, global suppression) and `packages/silk_intel/silk_platform` (its own queue, per-tenant suppression, no DB-CHECK approval layer) both implement cold-send. They disagree on I3 (`silk_platform/email_queue.py` has no `approved` status/CHECK — `migrations/platform/001_platform_core.sql:281-304`) and I4 (HIGH-8). Maintaining two send stacks multiplies the compliance surface. → Consolidate on one send pipeline, or document which is canonical and gate the other off in production.
- **MEDIUM — `emails`/`contacts`/`buyers` are not directly tenant-scoped; isolation depends on remembering to join through `campaigns`.** `apps/api/app/models/email.py:44-62` (no `factory_id`); any query that forgets the join leaks one factory's emails to another. → Denormalize a `factory_id` onto `emails` or adopt Postgres RLS. (`buyer_discovery` shares the Buyer/Contact/Shipment graph cross-tenant *by design* — `services/buyer_discovery.py:89-90` — which is acceptable but means PDPL erasure on a contact affects every matched tenant; make it a conscious decision.)
- **LOW — `silk_data_layer_v2` is not a version successor** but a derived-indicator layer on top of v1; both are imported live (`silk_market_ranker.py:15-21`). The architecture-map skill already lists this as a naming trap. → Rename to `silk_data_derived` in a mechanical PR.
- **INFO — `me-south-1` (Bahrain) is outside Saudi Arabia** and may not satisfy strict PDPL data residency (`infra/terraform/variables.tf:1-5`). Documented trade-off; confirm with counsel.
- **INFO — `infra/terraform/**` is a non-functional skeleton** (all modules are `null`/TODO stubs); the real deploy path is Railway. The audited cloud vulns (public S3, open SGs) have no implementation to be vulnerable — but the directory reads as deployable. → Label it non-deployable until built.

## 2. Security issues (beyond CRITICAL/HIGH above)

- **MEDIUM — Rate-limit identity trusts an attacker-controlled `X-API-Key` header on unauthenticated endpoints.** `packages/silk_intel/silk_intel/api.py:769-801` (identity 773-774). On public routes that call only `_rate_limit` (`/resolve`, `/config`, `/markets`, `/sources`, `/research/readiness`), rotating the header mints a new bucket every request, defeating the limit; there is no `X-Forwarded-For` parsing so all anonymous callers otherwise share one bucket. `/research/readiness` can drive unthrottled live Comtrade. → Key public routes on trusted client IP; only use `X-API-Key` as a bucket key after it matches.
- **MEDIUM — Smartlead webhook signature verification fails open when the secret is unset.** `apps/api/app/api/webhooks.py:36-43`. With `smartlead_webhook_secret=""` (default), `/webhooks/smartlead` is unauthenticated and state-mutating: a forged `{"event":"complained","message_id":…}` adds an address to the **global** suppression ledger and poisons deliverability metrics (auto-pausing campaigns). → Require the secret in production (non-mock provider); fail closed unless an explicit dev flag is set.
- **MEDIUM — Tenants can self-attest SPF/DKIM/DMARC and lift their own send gate.** `apps/api/app/schemas/common.py:52-54` exposes `spf_ok/dkim_ok/dmarc_ok` as tenant-writable; `PUT /factory/deliverability` (`api/factories.py:29-41`) mass-assigns them; `deliverability.can_send` gates on them — contradicting the staff-only `admin.mark_dns_verified` (`admin.py:59`). The web UI encodes this as a self-toggle button (`settings/deliverability/page.tsx:44-53`). → Remove the DNS flags from the tenant-writable schema; drive them from a real server-side DNS check.
- **MEDIUM — Unbounded product-image upload read fully into memory.** `apps/api/app/api/products.py:37-41` does `await image.read()` with no size cap and stores the client-supplied content-type verbatim. Multi-GB "images" exhaust worker memory. → Enforce a max size (streamed byte count), validate magic bytes, cap dimensions.
- **MEDIUM — Interactive competitor endpoint triggers uncapped live Comtrade calls (budget bypass).** `apps/api/app/services/competitor_snapshot.py:28-30` via `api/markets.py:24-27`. `GET /markets/{iso2}/competitors` calls `build_snapshot` with no `budget_scope`, so `api_budget.charge` returns True (unmetered) and an authenticated user can enumerate `(hs,iso2)` pairs to drive unbounded live calls, bypassing the ≤150/analysis ceiling. → Wrap the interactive call in a `budget_scope`; add a per-user rate limit.
- **MEDIUM — Plaintext OTP written to application logs.** `apps/api/app/services/auth_service.py:88` logs `code_for_local_delivery=code`. Anyone with log access reads live OTPs. → Never log the code.
- **MEDIUM — Login throttle keyed on `email|ip` doesn't limit horizontal password-spraying.** `packages/silk_intel/silk_intel/silk_platform/throttle.py:34,45-51`. One IP can try one attempt each against thousands of emails and never trip the per-pair counter; rotating IPs against one email also defeats it. → Add aggregate limiters keyed on IP alone and email alone.
- **MEDIUM — Anthropic email-drafting adapter interpolates untrusted context into the prompt with no A5 isolation.** `apps/api/app/providers/llm/anthropic.py:60-110` + `llm/prompts.py:84-107`. Buyer/company/contact/import-evidence strings reach Claude via plain f-strings — a prompt-injection surface the engine-side A5 rule forbids. Bounded (human-approval before send) but real. → Route external fields through an isolation/fenced-escaping helper.
- **MEDIUM — Real Gmail/Microsoft OAuth flows omit PKCE.** `apps/api/app/providers/sending/gmail_oauth.py:57-86`, `microsoft_oauth.py:63-90` run authorization-code with `state` only. → Add `code_challenge`/`code_verifier` (S256).
- **MEDIUM — Audit-log append-only trigger is bypassable by TRUNCATE.** `apps/api/alembic/versions/0001_initial.py:411-417` is a row-level `BEFORE UPDATE OR DELETE` trigger; row-level triggers don't fire on `TRUNCATE`, so `TRUNCATE audit_log` wipes the trail — and `tests/conftest.py:97` relies on exactly this to clear the log. Contradicts the "cannot be rewritten" guarantee. → Add a statement-level `BEFORE TRUNCATE` trigger that `RAISE`s, and revoke TRUNCATE from the app role. (The `silk_platform` `audit_log` has **no** immutability trigger at all — `migrations/platform/001_platform_core.sql:90-102` — MEDIUM: add `trg_audit_no_update/no_delete` mirroring the ledger/consent triggers.)
- **MEDIUM — Engine dashboard persists the privileged service `X-API-Key` in `localStorage`.** `packages/silk_intel/silk_intel/web/index.html:382,1294`. The key gating the paid surface is XSS-exfiltratable, unlike `platform.html`'s in-memory token. → Hold it in memory only (or use an HttpOnly session cookie).
- **LOW — CORS credentialed-wildcard risk in both APIs.** `apps/api/app/main.py:54-60` and `packages/silk_intel/silk_intel/api.py:256` set `allow_credentials=True` with `allow_methods/headers=["*"]`; safe only because `CORS_ORIGINS` defaults to an explicit origin — a wildcard `CORS_ORIGINS` becomes a credentialed-wildcard hole. → Assert `cors_origins != "*"` when credentials are allowed; gate `/docs` behind non-prod.
- **LOW — `/settings/keys` overwrites process `os.environ` at runtime and persists provider keys** (`packages/silk_intel/silk_intel/api.py:1140-1159`); in open dev mode any caller can shadow the Railway key until reboot. → Gate behind a stronger owner key; don't mutate `os.environ`.
- **LOW — CSP allows `'unsafe-inline'` for `script-src`** (`packages/silk_intel/silk_intel/api.py:264-269`). → Move to nonce/hash-based script-src.
- **LOW — World Bank URL path interpolates `indicator`/`iso3` without validation** (`silk_data_layer.py:628`); model-reachable `../` could reach other WB endpoints (fixed host, so not SSRF). → Validate/`quote` the segments.
- **LOW — `serve_file` builds a filesystem path from a URL segment with no `..` normalization** (`silk_platform/api.py:1107-1122`, `storage.py:62-77`); safe only because the key is HMAC-signed. → `realpath`-assert the result stays under `storage_dir()`.
- **LOW — Password-reset requests have no rate limit and don't invalidate prior tokens** (`silk_platform/auth.py:147-164`, `api.py:376-398`) → enables reset-bombing; throttle and consume prior tokens.
- **LOW — One secret reused for Fernet key, MAC, and link signing with weak domain separation** (`silk_platform/crypto.py:34-59`, `tokens.py:54-61`). → Derive per-purpose subkeys via HKDF.
- **LOW — OAuth callback reflects `error`/`email` into the redirect URL without encoding** (`apps/api/app/api/sender_accounts.py:106-123`) → parameter injection into the SPA URL; `urlencode` the values.
- **LOW — `login`/`otp/request`/`otp/verify` have no rate limiting; OTP has no attempt cap** (`apps/api/app/api/auth.py:38-59`, `services/auth_service.py:92-102`) → online brute force of the 6-digit code within its TTL. Add per-IP/per-account limits + failure lockout.
- **LOW — Uploaded image content-type stored unvalidated** (`apps/api/app/services/storage.py:60-62` via `products.py:41`) → stored-XSS on the storage origin if an SVG/HTML is uploaded as `text/html`. Allowlist + magic-byte check + safe `Content-Disposition`.
- **LOW — Remote product-image fetch is an unguarded SSRF sink** (`apps/api/app/services/product_vision.py:60-67`): `httpx.get(url, follow_redirects=True)` with no host allowlist; safe only while `image_url` is system-set. → Restrict host/scheme, block private ranges, constrain redirects.
- **LOW — `fix_agent.py` is an unattended code-editing agent with `acceptEdits`+`Bash`** (`packages/silk_intel/silk_intel/fix_agent.py:109-117`); dev-only and not in CI, but an arbitrary-code-execution surface if ever automated. → Narrow tools, require explicit opt-in, document the risk.
- **LOW — `esc()` in `web/index.html:330` doesn't escape `'`** (unlike `platform.html`) → latent attribute-injection XSS. Add `"'":"&#39;"`.
- **LOW — `platform_ui_smoke.py:36-54` hardcodes seed passwords and forces bcrypt cost 4 into the real `os.environ`**; unsafe if `--base` points at a shared DB. → Refuse to seed unless the DB is a temp path.
- **LOW — Smartlead/ZeroBounce pass the API key as a URL query param** (`smartlead.py:132`, `zerobounce.py:36`) → key in proxy/APM logs. Vendor-imposed; scrub query strings from telemetry.
- **LOW — Ledger/audit `limit` query params accept negatives** → SQLite `LIMIT -1` = unbounded (`silk_platform/api.py:1141-1169,733-744`). Clamp via `_as_int(min=1,max=…)`.
- **LOW — Confidence Numeric columns have no CHECK range [0,1]** (`apps/api/app/models/buyer.py:57,128`, `shipment.py:36`, `analysis.py:64`) → a bad import can persist confidence 5.0, corrupting scoring. Add `CHECK`.

## 3. Performance issues

- **MEDIUM — SQLite opened with no `journal_mode=WAL` and no `busy_timeout`.** `silk_usage.py:59-76`, `silk_storage.py:110-117,535-560`, `silk_store.py:58-76`. Concurrent async-research threads + status polling + the scheduler thread produce `database is locked`; in the money guards this fail-closes a legitimate paid request, and unguarded `save_mission_checkpoint` (`silk_storage.py:551`) aborts an expensive run. → Set `PRAGMA journal_mode=WAL` + `busy_timeout` in every `_connect`; wrap the checkpoint write in try/except. *(Also a production blocker.)*
- **MEDIUM — Per-analysis data counter is one dict shared by parallel mission threads, mutated without a lock.** `silk_context.py:135-198`. `copy_context()` copies the var→value mapping, not the dict, so mission threads race `c[kind]+=n` / `row["input_tokens"]+=…`; lost updates undercount tokens that feed `estimate_cost_usd`→`reconcile_usd`, letting the daily USD cap be exceeded over runs. → Guard with a lock or per-thread accumulation merged at join.
- **MEDIUM — Mission/agent "timeout" is not a wall-clock bound.** `silk_missions.py:556-593`, `silk_research.py:1252-1268`. After the deadline, the `with ThreadPoolExecutor` exit calls `shutdown(wait=True)`, blocking until stuck threads finish; `fut.cancel()` can't cancel a running future. The declared deadline is cosmetic. → Use `shutdown(wait=False, cancel_futures=True)` and rely on hard per-call timeouts.
- **MEDIUM — Throttle's `min(wait, 5.0)` sleep cap defeats rate-limiting under fan-out.** `silk_data_layer.py:109-117`. It reserves each slot by the full gap but sleeps at most 5 s, so the 6th+ worker wakes early and fires before its reserved instant — the effective rate exceeds the intended ~1/1.1 s that the throttle was added to enforce. → Loop the sleep to the reserved instant or raise the cap.
- **MEDIUM — Cache-miss-on-fetch-failure triggers a second full fetch.** `silk_data_layer.py:494-499,636-640`. `_cached_get` already fetches; on failure the caller re-`_http_get`s with its own retry budget, doubling load on an already-unhealthy endpoint. → Distinguish "cache disabled" from "fetch failed" and don't re-fetch on the latter.
- **MEDIUM — `silk_gmaps.submit_scrape_async` leaks a non-daemon `ThreadPoolExecutor` per call.** `silk_gmaps.py:416-432`. The executor is never referenced or shut down; its non-daemon worker can poll up to 480 s after the caller gave up, delaying Railway redeploys and accumulating threads. → Use a module-level executor or a daemon thread and `shutdown(wait=False)`.
- **MEDIUM — `useApi` polling has an overlapping-request / out-of-order race.** `apps/web/src/lib/useApi.ts:26-32`. `setInterval(load, pollMs)` fires regardless of whether the prior request resolved; a stale response can `setState` over a newer one (flickering approval counts / reverting email status), and a late resolve `setState`s after unmount. → In-flight guard or request-id; `AbortController` on unmount; recursive `setTimeout`.
- **MEDIUM — pgvector `embedding` column has no ANN index despite the "indexing is real" docstring.** `apps/api/app/models/product.py:63` + all migrations (none create a vector index); `llm/embeddings.py:1-8` claims indexing is real. Similar-product/HS lookups do an O(n) sequential scan. → Add an `hnsw`/`ivfflat` index matching the query's distance op; or correct the docstring.
- **MEDIUM — Writer/reviewer/continuation tail is not bounded by the per-run LLM cap.** `silk_ai_judge.py:1241-1322,1592-1612` call `_call` directly, never consulting `data_counter()`; a single `/research` can run draft(×≤4)+continuation+reviewer(×1-2)+revision(×≤4) at up to 32k tokens each, far exceeding the advertised cap (only the daily money guard bounds it). → Gate the writer/reviewer tail on the same counter and degrade gracefully.
- **LOW — TrendsAgent issues 2–5 uncached pytrends calls per market** with stacked 429 backoff (`silk_trends_agent.py:438,450,381-409`); only the main call has snapshot resilience. → Give `_seasonality` the same store fallback or derive it from the one payload.
- **LOW — Request cache directory grows without bound** (`silk_cache.py:55-116`); TTL is mtime-only, stale entries are refetched but never deleted. → Periodic prune in the existing scheduler.
- **LOW — `/health` is unauthenticated, unthrottled, and does a volume `mkstemp` probe + DB opens on every call** (`packages/silk_intel/silk_intel/api.py:403-557`, `silk_storage.py:95-104`). → Rate-limit it; make the heavy sections opt-in (`?full=1`).
- **LOW — Circuit-breaker half-open admits a thundering herd of probes** (`silk_circuit.py:38-51`); the docstring promises "one probe" but every concurrent caller sees half-open. → Single-flight the probe under `_lock`.
- **LOW — ETL upsert inserts row-by-row and can leak the engine pool on error** (`etl/world_trade_sync.py:297-345`; `engine.dispose()` after the transaction block). → Batch insert; move `dispose()` into `finally`.
- **LOW — Redundant standalone index on `world_trade.hs6`** (leading column of the composite unique) adds write cost (`apps/api/app/models/world_trade.py:33`). → Drop it if no query needs `hs6` alone.

## 4. Code smells

- **MEDIUM — `_stage2` synthesis verdict uses the fragile `find('{')/rfind('}')` JSON extraction** the codebase replaced everywhere else (`silk_synthesis.py:73-77`); a fenced/trailing-brace response silently collapses the stage-2 verdict to `{"reasoning": out}`, losing the AI reasoning fed to the writer. `evaluate_report` (`silk_evals.py:253-254`) has the same bug (drops all four judge axes to None). → Reuse `silk_ai_judge._extract_json` (already imported).
- **MEDIUM — Eval judge prompt and writer catalog claim "15 sections"; the report is 11** (`silk_evals.py:221`, `silk_ai_judge.py:1623`; `_REPORT_SECTIONS` has 11). The judge systematically penalizes correct reports for four impossible sections, making `section_completeness`/regression scores unreliable. → Interpolate `len(_REPORT_SECTIONS)`.
- **MEDIUM — `gap_rate` silently skips live `AgentReport` missions** (`silk_evals.py:463-471` vs `run_case` at 413 which passes live objects), so a live golden run always reports 0% gaps and the gap-rate gate passes vacuously. → Normalize missions to dict shape or accept `AgentReport`.
- **MEDIUM — Module-load `int()/float(os.environ…)` with no guard crashes import on a malformed env var** (`silk_websearch_agent.py:132`, `silk_gmaps.py:63-64,340-341`, `silk_product_intake.py:24-31,100`); one typo'd env var fails the whole package/`api.py` boot, contradicting the "imports offline/keyless" invariant. `silk_trends_agent.py:25-40` shows the correct guarded pattern. → Wrap each parse in try/except with a default.
- **MEDIUM — Market-enrichment mock tags provenance `COMTRADE`; the live adapter tags `ENRICHMENT`** (`market_enrichment/mock.py:35` vs `worldbank_wits.py:81`). Different `SOURCE_QUALITY` weights mean scoring silently changes the day a key is added. → Change the mock to `ENRICHMENT`.
- **MEDIUM — Coresignal live adapter always returns `key_people=[]`; the mock always populates it** (`enrichment/coresignal.py:66` vs `mock.py:45-51`). Decision-maker seeding works in every demo/CI run and returns nothing in production. → Map the real payload or make the mock match.
- **MEDIUM — Outscraper response-mapping loop sits outside the try/except** (`maps/outscraper.py:38-63`), so malformed vendor data crashes the discovery run — defeating the stated I1 degrade-to-`[]` guarantee. → Move the loop inside the handler.
- **MEDIUM — Apollo finder with a missing domain returns wrong-company contacts** (`email_finding/apollo.py:40-56`); `q_organization_domains: domain or ""` runs an unscoped people search that attributes arbitrary contacts to the queried company (an I1 fabricated association). → Skip Apollo when domain is falsy.
- **MEDIUM — `_normalize` awards a full 1.0 to a component present in only one market** (`silk_market_ranker.py:594-608`); scarcity masquerades as strength and moves the (non-confidence-weighted) sort key. → Return a neutral 0.5 for a degenerate distribution, or fold confidence into the sort.
- **LOW smells (file:line → fix):**
  - `_competition_component` returns HHI 0.0 (fabricated "easiest market") when competitors exist but no share is known — `silk_market_ranker.py:575-591` → return `None@0.0`.
  - `compute_source_coverage` returns 100% for an empty report — `silk_source_coverage.py:98` → return 0.0 / "no indicators".
  - `validate_market_row` doesn't flag a negative `market_size` — `silk_quality.py:47` → add a `<0` branch.
  - `muslim_share` module-global cache filled lazily without a lock, raced by orchestrator threads — `silk_research.py:1000-1018` → lock or precompute.
  - Watchdog `_check_no_fabrication` flags a real observed `0`/`False` at confidence 0.0 as fabrication — `silk_watchdog.py:437-455` → treat numeric 0 as empty-equivalent.
  - Watchdog attributes service failures by a time window (cross-attributes under concurrency) — `silk_watchdog.py:481-519` → stamp `analysis_id`.
  - FAOSTAT item match uses substring `in` (wrong-commodity selection) — `silk_faostat_agent.py:138-144` → prefer exact/word-boundary.
  - GDELT retry uses a blocking, non-injectable `time.sleep` — `silk_gdelt_agent.py:67` → expose injectable `_sleep`.
  - `_extract_json` type hint says `list` but can't parse a top-level array — `silk_ai_judge.py:124-143` → narrow the hint or handle `[`.
  - `_index_search` ignores `limit` for an empty query — `packages/silk_intel/silk_intel/api.py:54-55` → honor `limit` in both branches.
  - `verified_contacts` uses a top-5 denominator vs `total_contacts` over all — `apps/api/app/services/report.py:258-267` → count over the same population.
  - `WebhookEvent.event` is a bare `str`; unknown events silently no-op — `apps/api/app/schemas/campaign.py:86-89` → `Literal`/enum.
  - Anthropic `_extract_json` fenced-block `split("```")[1]` assumes a closing fence — `apps/api/app/providers/llm/anthropic.py:113-127` → tolerant extractor.
  - `_oauth_http.exchange` raises bare `KeyError` on a 2xx body lacking `access_token` — `apps/api/app/providers/sending/_oauth_http.py:55-64` → typed error.
  - India numeric coded `699` (Comtrade) under a field docstring'd "UN M49" (356) — `apps/api/app/providers/countries.py:20` → rename/comment.
  - `esc()` single-quote gap (see Security). Duplicate `t("dailyCap")` label prints the wrong string — `apps/web/.../settings/deliverability/page.tsx:75-78`. Hardcoded English admin tabs / raw enums (see Prompt-compliance I10). API paths interpolated without `encodeURIComponent` — web `products/[id]/{markets,buyers,report}` pages. Nonsensical `{t("nameAr") && "×"}` close button with no `aria-label` — `apps/web/.../products/page.tsx:130`.
  - Status/basis columns are free `String`s, not enums/CHECK — `apps/api/app/models/{product.py:59-61,analysis.py:35-37,buyer.py:100}`; `lawful_basis` free+nullable means a lead can lack a basis. → Enums/CHECK; NOT-NULL gate for lawful_basis.
  - Confidence range CHECK missing (see Security). Redundant in-loop imports — `silk_reports.py:1734,1799`, `silk_render.py:1768`. Redundant `import hashlib` in mock sender — `apps/api/app/providers/sending/mock.py:103-104`.

## 5. Prompt-compliance issues (I1–I10 / A1–A12)

*(HIGH-2 I5/A4 copy_context, HIGH-6 I9, HIGH-8/9 I4, HIGH-10 I4/I6/I8 are above.)*

- **MEDIUM — I2: auto HS-resolution can bypass the human confirmation gate on a 0.5-confidence web snippet.** `silk_hs_attributes.py:843-850` → `silk_hs_confirm.py:754-759`. When `SILK_HS_ATTRIBUTE_RESOLVE=1`, a web-proximity match (`conf=0.5`) returns `block=None`, so the 422 human gate is not raised and the paid analysis proceeds on an unconfirmed code. Gated off by default (why it's MEDIUM), but an I2 bypass the moment the flag flips. → Never let a `resolved_from="web"` result set `block=None`.
- **MEDIUM — I6: tenant SMTP host is unrestricted — cold outreach can route through a transactional ESP.** `silk_platform/email_queue.py:91-108`, `smtp_transport.py:85-118`, `api.py:1014-1041`, `repository.py:26-28`. A factory can set `host=email-smtp.*.amazonaws.com` / `smtp.sendgrid.net` and blast cold outreach through exactly the ESP class I6 forbids. → Add an ESP denylist/provider allowlist at `create_smtp`/send.
- **MEDIUM — A3: forecast scenario numbers are computed in the docx consumer, not `build_view`.** `silk_reports.py:3780-3793` derives YoY % and conservative/base/optimistic scenarios at render time, and `render_markdown` has no equivalent — the two derivatives diverge, the exact failure `build_view` exists to prevent. → Compute scenarios in `build_view`; both consumers read them.
- **MEDIUM — A5: `verdict["note"]` reaches the auditor docx and markdown unsanitized.** `silk_reports.py:1878-1880,4067-4069`; only `verdict.ai.reasoning` is stripped in `build_view` (`silk_render.py:1780-1784`). Any internal token/field name in `verdict.note` leaks into the operator `.md`/Word artifact. → Sanitize `verdict["note"]` once in `_deep_research_view`.
- **MEDIUM — A5: the `/analyze` executive summary renders `ai_report` (Claude) without the sanitizer.** `silk_render.py:2183` attaches `result.get("report")` raw; `silk_reports.py:893-895` (consumed at 3576/4190) drops it into the report body while every other narrative is sanitized. → `_strip_internal_plumbing` at the boundary.
- **MEDIUM — decision #4 / A1: the unified contract adapter reads `sources` but `DataPoint` exposes `source_ids`, silently dropping multi-source attribution.** `packages/contracts/contracts/__init__.py:126` does `getattr(dp,"sources",())` which never matches, so composite attribution (the HF1 fix) is lost on every adapt. → Read `source_ids`; add a round-trip test.
- **MEDIUM — I10: hardcoded English admin tab labels bypass next-intl; Hindi wrongly treated as RTL.** `apps/web/.../admin/page.tsx:25,31,39,71` render raw enum keys (`factories`/`suppression`/`audit`/`DNS`) untranslated in the Arabic default locale; `EmailReviewSplitView.tsx:118,126` marks `hi` (Devanagari, LTR) as RTL, mirroring Hindi outreach copy. → Add message keys; drive direction from a proper RTL set (ar/ur/he/fa). *(Also `BuyerCard.tsx:33` renders `buyer.source` raw; seed sets `description_ar` to the English string — `seed.py:201-202`.)*
- **LOW — A5: `role` isolated at `silk_ai_judge.py:370` but injected raw at :373** — latent injection if a future caller threads an external role. → Isolate at :373.
- **LOW — A8: the apps/api Comtrade adapter serves committed fixtures at `confidence=0.9` with no "stale"/«من المخزن» note after a live failure** (`shipments/comtrade.py:164-175`), so a consumer can't tell a live figure from a years-old fixture. → Attach a staleness marker/lower confidence.
- **LOW — I8/I10: follow-up drafts carry the parent's stale HTML body and unsubscribe token.** `apps/api/app/workers/tasks.py:354-369` sets the new follow-up text but `body_html=original.body_html` while minting a new token — text/HTML mismatch and a wrong unsubscribe link (CAN-SPAM hazard). → Re-render HTML from the follow-up's own text+token.
- **INFO — I2 seed shortcut auto-confirms HS with a `None` confirmer** (`seed.py:210-213`); verify `confirm_hs_code` rejects a null confirmer on all non-seed paths.
- **INFO — I3 is not reproduced in the `silk_platform` send pipeline** (no approval status/DB-CHECK — `migrations/platform/001_platform_core.sql:281-304`); document that I3 is owned by `apps/api` or add the CHECK layer.
- **Positives confirmed:** A1 (no fabricated zeros; malformed records dropped; inferred-zero cap ≤0.6), A2 (single verdict path), A5 (engine-side isolation of value/source/note/hs_code/steer), A7 (money guards `BEGIN IMMEDIATE`, fail-closed, never refunded), A9 (correlation zero external calls — AST-tested), A10 (all migrations additive), A12 (uncited claims dropped). In `apps/api`: I3 (API + worker `SELECT..FOR UPDATE` + DB CHECK `ck_emails_sent_requires_approval`), I4 (global suppression checked last before egress, append-only trigger), I5 (deepen scope re-established per worker task), I6 (Smartlead, not a transactional ESP) — all present and correct.

## 6. Dead code

- `silk_narrative.brief_lines` — third stale implementation of the brief, test-only caller (`silk_narrative.py:699-718`).
- `silk_usage.record_paid_calls` — superseded by the atomic reserve, no production caller (`silk_usage.py:97-109`).
- `silk_usage.would_exceed_usd_cap` — wired only into a test (`silk_usage.py:169-178`).
- Duplicate unreachable `return flags` (`silk_plausibility.py:320-321`).
- Consumer-culture disable check runs *after* the layer already executed → the skip assignment is dead and the disable never happens (`silk_engine.py:271-284`) — *also a compliance bug (disabled "consumer" agent still makes a Claude call)*.
- `tools/dev_console.py` — orphaned Streamlit UI on an uninstalled dep (`1-136`).
- `ProductCreate` schema — never imported; endpoint uses `Form(...)` (`apps/api/app/schemas/product.py:9-16`).
- `decodeRole` dead ternary + unreachable `: null` after `redirect()` (`apps/web/.../(app)/layout.tsx:15,27`).
- Unused ar/en message keys (`markets.share`, `products.confidence`, `buyers.evidence`, `campaign.subject/queue`, `nav.settings`).
- Comtrade adapter's `self._timeout` never used (`apps/api/app/providers/shipments/comtrade.py:49-54`); `AuditLog` `TimestampMixin.updated_at`/`onupdate` dead under the immutability trigger (`compliance.py`).
- Stale docstrings (doc rot, adjacent to dead code): `AUDIT_APPENDIX_CAP` says 80, is 150 (`silk_quality_gate.py:919`); `silk_gmaps.py:12-15` claims C2–C5 "not opened" while wired into `api.py`.

## 7. Missing tests

*(CRITICAL-3, HIGH-15 above.)*

- **MEDIUM — `apps/api/app/services/storage.py` has zero test coverage** (the report-artifact backend; put/get, `STORAGE_BACKEND` switch, missing-object). → Add a storage round-trip test.
- **MEDIUM — OAuth token crypto tests omit ciphertext-tamper/integrity** (`apps/api/tests/test_sender_accounts.py:101`); a tampered blob is never asserted to fail decryption (Fernet is AEAD, so this should hold — but it's unproven). → Assert `decrypt(tamper(ct))` raises.
- **MEDIUM — `silk_seed_data.py` (live World-Bank-failure fallback) has no hermetic test** (`grep tests/` → 0). → Assert known ISO3→(value,year), unknown→None, missing CSV→empty.
- **MEDIUM — No test guards the copy_context threaded research path** (HIGH-2) or counter integrity under parallel `record_llm_usage`. → Threaded hermetic tests.
- **LOW — No regression test asserts API keys are absent from failure notes/logs** (HIGH-4/5). No test asserts OTP `dev_code` is withheld outside local (CRITICAL-1). Tautological `assert … is not None or True` (`test_rung2_real_server.py:69`, and that file never runs in CI anyway). No test for the inconclusive-verdict render (HIGH-1). `packages/contracts` ships zero tests, which is why the `source_ids` bug went unnoticed. No cross-tenant SMTP-ESP rejection test; no post-send consent+debit rollback test (HIGH-9).
- **LOW — `importorskip` soft-gating turns ~40+ report/docx/API tests into silent skips if a dep drifts** — the wrong failure mode for CI (a missing `requirements.txt` line converts the whole report surface to green skips). → A collection-time hard import assertion in the CI lane.

## 8. Technical debt

- Engine CI (`.github/workflows/ci.yml`) runs **only** `pytest tests/ -q` + a text self-review gate — no linter (CLAUDE.md confirms none), no coverage floor, no type-check; I7 is "CI-linted" only via an in-suite AST test, not a lint step; the heavier gates are `workflow_dispatch`-only or branch-protection-dependent. → Add ruff + coverage + explicit pandas-guard steps.
- `apps/api/Dockerfile:4` copies `uv:latest` (unpinned supply chain); both `FROM` tags are floating (`python:3.11-slim`, `node:22-slim`) — non-reproducible. → Pin by digest.
- Engine `Dockerfile:18-21` `curl`s fonts from `github/fonts@main` (mutable, no checksum) — a build-time SPOF and supply-chain hole. → Vendor the TTFs or pin a SHA + `sha256sum -c`.
- CI builds web with pnpm 10 while the image builds with pnpm 11.18.0 and `package.json` has no `packageManager` field — green CI doesn't prove the prod build (`ci.yml:126,148` vs `apps/web/Dockerfile:12`). → Add `packageManager` and align.
- Web image is single-stage (ships devDeps + full source, no `standalone`). → Multi-stage.
- CI installs `pytest`/`httpx`/`pymupdf` unpinned (`ci.yml:23`). → Pin dev tooling.
- `.gitignore` gaps: no `*.tfvars`, `.env.production`/`.env.staging` not ignored, `.terraform.lock.hcl` wrongly ignored (`.gitignore:27-30,43-47`).
- "Portable SQLite/Postgres" migration claim is false — `RAISE(ABORT)` triggers + `executescript` are SQLite-only, so the DB-enforced ledger/consent immutability (I4) would silently not exist on Postgres (`migrations/platform/001_platform_core.sql:132-137,266-268`). → Drop the claim or provide dialect-guarded Postgres trigger functions.
- FAOSTAT breaker is a process-global with no TTL/half-open — one transient 401/403 permanently disables FAOSTAT for all tenants until redeploy (`silk_faostat_agent.py:31,108-113`). → TTL/half-open reset.
- `SILK_MAX_REVIEW_CYCLES=1` (default) means the reviewer never triggers an auto-revision (`silk_ai_judge.py:1592-1604`) — blocking findings are left for the quality gate to FAIL rather than self-heal. → Comment/allow one blocking-only revision.
- DB connections from `with _connect(...)` are never closed (relies on CPython refcount GC), inconsistent with `silk_platform` (`silk_usage.py`/`silk_storage.py`/`silk_store.py`/`silk_ops_log.py`). → `contextlib.closing`.
- `etl/hs_reference_sync.run()` raises `NotImplementedError` but README/Makefile advertise it as runnable (`etl/hs_reference_sync.py:27-29`). → Mark "(Phase 3)".
- Anthropic (apps/api) and Smartlead adapters have no retry/backoff on transient 429/5xx (`llm/anthropic.py:32-41`, `sending/smartlead.py:130-143`); anthropic also discards `usage`/cost signal. → Bounded retry + capture usage.
- Mock providers anchor to hardcoded years (`shipments/mock.py:88,128,163` → 2026; `seed.py:249,267` → base_year 2023) that rot as wall-clock advances. → Single configurable demo-epoch.
- `test_regression_registry.py` is a 2152-line monolith; ~138 files hard-couple to exact Arabic strings (A11 by design, brittle); several timing tests use real wall-clock `time.sleep` (`test_stage3_research.py:151` etc.). → Split the registry; centralize contract strings; fake clocks.
- `.ps1` deploy sets `STORAGE_BACKEND=local` + "nothing left to set" → uploaded images wiped on redeploy (`deploy-to-railway.ps1:268,300-303`). → Attach a Volume or default to s3. *(Also a data-loss production blocker.)*
- `apps/api` sets no explicit DB pool sizing (`db.py`) — tune for prod. `docker-compose` `beat` depends only on redis while receiving `DATABASE_URL` (`infra/docker-compose.dev.yml:82-92`).
- Sample generators run side-effects (disk write + `os.environ` mutation) at import (`tools/gen_research_sample.py:307-328`, `gen_kuwait_battery_sample.py`), unlike the fixed `gen_client_report_sample.py`. → Guard under `__main__`.

## 9. Production blockers (consolidated)

The blocking items, cross-referenced to their detail above:

1. **CRITICAL-1** OTP code in response → account takeover — `apps/api/app/api/auth.py:55-58`.
2. **CRITICAL-3** Rungs 2–3 / live-smoke unwired in CI — release gate is fictitious.
3. **HIGH-1** INCONCLUSIVE verdict KeyError crashes all deep-research exports — `silk_reports.py:732`.
4. **HIGH-10** Unproven Smartlead cold-send with no verified one-click unsubscribe — `providers/sending/smartlead.py`.
5. **HIGH-11** Containers run as root — `Dockerfile`s.
6. **HIGH-13** Railway deploy provisions non-pgvector Postgres → api crash-loop — `deploy-to-railway.sh:217`.
7. **HIGH-7 / MEDIUM(WAL)** Unbounded SWR Comtrade fan-out and `database is locked` aborting paid runs — `silk_data_layer_v2.py:304`, `silk_storage.py:551`.
8. **MEDIUM** No app-level rate limit, request-size cap, or security headers on `apps/api`; `/docs` exposed in every env — `apps/api/app/main.py:42-90`.
9. **MEDIUM** `emails.approved_by ON DELETE SET NULL` vs the sent-requires-approval CHECK → any approver of a sent email can never be deleted (blocks GDPR/PDPL erasure + offboarding) — `apps/api/app/models/email.py:82-84` + `0001_initial.py:358-359`.
10. **MEDIUM** `.ps1` deploy loses uploaded images on redeploy — `deploy-to-railway.ps1:268`.
11. **INFO/open** Residual writer `report=None` tail survives the escalation/continuation machinery (`silk_ai_judge.py:1269-1277`) — the known open case; a streaming/section-by-section write is the standing candidate fix.

---

## Coverage statement

Every source file in the repository was inspected top-to-bottom by a dedicated reader: all 71 engine top-level modules, all 28 `silk_platform` modules, all 33 `tools/`, all of `apps/api` (routes, 32 services, workers, schemas, 27 providers, 14 models, 11 Alembic migrations, seeds), all 35 `apps/web` `.ts/.tsx` + messages + 9 e2e specs, `etl/`, `infra/` (compose + terraform), `packages/contracts`, the 8 SQL migrations, both HTML dashboards, all Dockerfiles/CI/deploy scripts, and the 259-file test tree (inventoried; suspicious files read in full). Governing specs (MASTER_PROMPT I1–I10, change-rules A1–A12) were read directly and used as the compliance rubric.

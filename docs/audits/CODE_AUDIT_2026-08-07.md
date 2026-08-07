# Repository Audit — Silk United (Pre-Launch Comprehensive Review)

**Date:** 2026-08-07 · **Type:** independent read-only pre-launch audit (no business logic changed) ·
**Baseline:** HEAD `c775199` (post-PR #89/#90, Wave 3) · **Follow-up to:** `CODE_AUDIT_2026-08-06.md`

**Method:** six parallel read-only dimension passes (prior-audit fix verification ·
architecture & code quality · HS-classification + market-analysis feature depth ·
outreach/campaign/email + button-by-button UI wiring · security · reliability &
performance), each anchored to `file:line` at HEAD. In parallel, the verification
suites were **actually executed in this audit environment** — including, for the first
time, the API suite against a real migrated Postgres 16 + pgvector + Redis, a live boot
of the API server with HTTP probes, and the golden-path demo pipeline end to end
(§2). No paid or live vendor APIs were called; no `.env` contents were read; no secret
values are reproduced.

---

## 1. Executive summary — readiness score: **6.5 / 10**

Up half a point from the 2026-08-06 audit's 6/10, and the direction of travel is
genuinely good: of that audit's nine critical blockers, **seven are verifiably fixed in
code with regression tests** (dead unsubscribe route, mailbox bounce detection,
double-send/lost-task, pipeline error recovery, live-price registry keying, login
lockout DoS, CI gating hole), and two are partially fixed (demo-seed screening, image →
vision on the default deploy). The send-path core — three-layer human approval gate,
two-phase at-most-once send claim, global suppression re-checked at egress, stale-claim
reaper — is now production-grade engineering, and this audit reproduced the whole
golden path live against a real database.

What holds the score at 6.5 rather than 7+ is that the central finding of every prior
audit is **still true at HEAD**: this is a bulletproof demo strapped to an unproven
production path. Three of this audit's discoveries sharpen it:

- **The flagship feature cannot work on the shipped artifact.** The world-market screen
  depends on `sync_world_trade`, which does `from etl import world_trade_sync` — but
  `etl/` and its dependencies are **not in the production image** (`apps/api/Dockerfile`
  copies only `apps/api` + `packages`), and the deploy script additionally sets
  `COMTRADE_OFFLINE=1`. Every real product's analysis fails with *"a coverage sync has
  been requested — retry in a few minutes"* — a promise that can never be kept. The test
  that "proves" the sync injects a fake `etl` module (`test_world_trade_coverage.py`).
- **The documented deploy still breaks storage-dependent features.**
  `deploy-to-railway.sh` ships `STORAGE_BACKEND=local` on a four-container topology:
  the uploaded product image silently never reaches the vision model, and — new since
  Wave 3 — the executive report is written to the *worker's* disk and downloaded from
  the *API's* disk, so **every executive report download 404s in production** while all
  tests pass.
- **Keyless production fabricates client-facing data.** Sending fails closed without
  keys (good), but observed prices do not: a keyless deploy persists mock prices with
  invented competitor names and `listings.example` URLs into `MarketSnapshot` and
  renders them in the client-facing executive docx. Mock market enrichment is likewise
  stamped `COMTRADE`, and demo-seed rankings are rendered as "الأمم المتحدة (كومتريد)".

Additionally, **"ad campaigns" as a claimed main feature does not exist** — no model, no
route, no stub; "campaigns" means cold-email outreach only. Smartlead is honest
fail-closed scaffolding (no campaign-id mapping, webhooks unwired); the Gmail/Microsoft
mailbox path is code-complete but has never been proven against a real provider — the
dispatchable live-smoke lane built for exactly that purpose has never been run.

Score decomposition: engineering discipline **8.5/10** · mock-mode product completeness
**8.5/10** · live-path readiness **4/10** · operations readiness **5.5/10**. The prior
audit's proposed launch gate stands unmet: **no real end-to-end pilot campaign with real
keys has ever been exercised.** Most fixes below are days, not weeks.

### Severity totals (this audit, deduplicated)

| Severity | Count | Theme |
|---|---|---|
| Critical | 7 | ETL absent from shipped image · storage-broken default deploy (vision + report 404) · mock prices/enrichment fabricate client data in keyless prod · sends stranded in `queued` forever · live paths never proven (launch gate unmet) · legacy engine API open-by-default if deployed · "ad campaigns" claim has zero backing |
| High | 8 | demo data invisible to users + mislabeled as Comtrade · blocking I/O in async handlers · buyers N+1 polled every 4s, no terminal state · discovery task fire-and-forget · no alerting / beat liveness / queue metrics · Gmail MIME header injection · UI renders errors as empty states · unsafe `TRUSTED_PROXY_COUNT`/`API_BASE_URL` defaults |
| Medium | 12 | see §7 |

---

## 2. Verification evidence (actually executed in this audit)

| Lane | Command | Result |
|---|---|---|
| Pandas guard (I7) | `python3 tools/check_no_pandas.py` | ✅ pass |
| Data contracts | `pytest packages/contracts/tests` | ✅ 9 passed |
| Engine hermetic suite | `pytest` in `packages/silk_intel` | ✅ **2,569 passed, 0 failed** (two full runs, exit 0) |
| API lint | `ruff check` + `ruff format --check` | ✅ pass |
| API suite | `pytest` vs **real migrated Postgres 16 + pgvector + Redis** | ✅ **463 passed, 0 failed** (90 test files) |
| Web | `pnpm lint` + `tsc --noEmit` + locale parity + `next build` | ✅ pass — 362 keys identical ar/en |
| Playwright e2e | `pnpm test:e2e` (mocked APIs, real Chromium) | ✅ **35/35 passed** (2.3 min) incl. full journey login→upload→HS→funnel→discover→campaign→approve |
| Migrations | `alembic upgrade head` on fresh Postgres | ✅ linear 0001→0020, clean |
| Seed + golden path | `app.seeds.seed` + `app.seeds.demo_golden_path` (real DB/Redis, eager Celery) | ✅ full pipeline: intake → HS → funnel → discovery → Hindi draft + compliance footer → approval gate refuses pre-approval queue → guarded mock send → engagement → dashboard |
| Live API boot | `uvicorn app.main:app` + HTTP probes | ✅ `/health` all deps ok · login JWT · tenant-scoped `/products` · `/u/{token}` 200 · confirmed `/metrics` + `/docs` unauthenticated |

A full `docker compose` boot of all seven services was also attempted but Docker Hub
image pulls were rate-limited/blocked in the audit sandbox; the compose file itself is
sound, and the API/worker code paths it exercises were verified directly against the
locally provisioned Postgres + Redis instead (rows above).

The one thing **no lane anywhere proves** — including CI — is any live vendor path:
Comtrade sync (`etl/world_trade_sync.py:212` carries an explicit in-code "unverified
against the live API" warning), Gmail/Microsoft OAuth send, real NDR bounce parsing,
SerpApi prices. The `live-smoke.yml` workflow exists precisely for this and has never
been dispatched.

---

## 3. Architecture & code quality — sub-score **6.5/10**

Two codebases of very different quality share one repo, joined by a genuinely clean seam.

**Strengths (verified, not politeness):**
- `apps/api` alone is 8+/10: clean api/services/providers/workers layering, protocol-based
  provider registry with deterministic mocks and fail-closed live slots, fail-closed
  config (`config.py:206-241` rejects dev `SECRET_KEY`/blank `TOKEN_ENCRYPTION_KEY`
  outside local), thoughtful worker error taxonomy (transient/permanent split, the
  `SoftTimeLimitExceeded` reclassification, `tasks.py:40-74`).
- The body/brain seam is exemplary: `app/services/engine.py` is the single adapter;
  only ~7 engine modules are imported across all of `apps/api`; dependencies flow one
  way; `packages/contracts` is a 147-line frozen dataclass done right.
- Defense-in-depth on dangerous legacy: `silk_platform` is excluded by `.dockerignore`
  *and* a build-time guard *and* a lock test.
- The harness (`.claude/`, ADRs, invariant/AST-guard tests) matches reality.

**Weaknesses:**
- The engine (~4.5/10 alone): 72 modules installed flat into the **root namespace**
  (`pyproject.toml:62-135` — top-level modules literally named `api`, `correlation`,
  `fix_agent` in the prod venv); god-files (`silk_reports.py` 4,883 lines, `api.py`
  3,355, `silk_render.py` 2,469); ~120 test assertions grep **source text**, locking
  function names and layout so the god-files can effectively never be decomposed.
- The 222-file engine test suite is an accretion log organized by PR history
  (`test_wave1…13`, `test_pr147_review_fixes`) — assertion content is often genuinely
  behavioral, but finding "the ranker tests" requires archaeology.
- Duplicated concepts body vs brain: two Anthropic adapters, two caches (disk JSON vs
  Redis), two config systems coupled only by env-var-name convention (a seam that
  already caused one production bug, per `config.py:75-81`); `silk_data_layer_v2.py`
  extends v1 rather than replacing it — misleading name, not dead code.
- Dead-in-prod weight ships in the image: ~15 unreachable engine modules, 12 MB of
  engine tests, the 772 KB legacy standalone frontend (`web/index.html` +
  `platform.html`), `samples/`, plus pre-merge leftovers `netlify.toml` /
  `railway.json` (whose `startCommand` boots the superseded `uvicorn api:app`).
- Engine code uses `print()` (125 calls) and CWD-relative paths (`silk_cache.py` writes
  `data/cache` relative to wherever the worker happens to start); 323 broad
  `except Exception` handlers are deliberate house style, annotated, but a real bug
  degrades to "no data" instead of surfacing.
- The vendored engine `CLAUDE.md` still mandates the pre-merge standalone product —
  an agent editing the engine receives instructions contradicting the monorepo.

---

## 4. Feature readiness

### 4.1 Product intake + HS classification — **COMPLETE** (one deploy caveat)
The strongest feature. Real path traced end to end: bounded 10 MB upload with
content-type sanitization → storage-interface key → worker vision (real base64 image
blocks to Anthropic Messages API) → deterministic-first HS classifier grounded on the
full WCO nomenclature with a no-fabrication validation gate (`silk_hs_classifier.py:245`
rejects codes outside the 6,941-row reference) → single-writer confirm endpoint.
Keyless degradation is honest: declared failure, never invented candidates.
**Caveat:** on the scripted Railway deploy (`STORAGE_BACKEND=local`, four containers)
the image never reaches the vision model — ERROR log only, no user-visible signal (§5 C2).

### 4.2 Market analysis / screening / prices / reports — **PARTIAL: excellent machinery, hollow data supply**
- **Screening data:** still the 14-importer × 6-HS demo seed, seeded **local-only**.
  New since 08-06: coverage classification, loud failure on `none`, on-demand sync task
  + daily refresh beat. **But the sync is structurally dead in production** — `etl/` is
  not in the image and `COMTRADE_OFFLINE=1` is the deployed default (§5 C1). A real
  product's funnel fails forever with a retry message that can't succeed.
- **Stage 2 enrichment:** live WorldBank/WITS adapter exists but nothing ever sets
  `MARKET_ENRICHMENT_LIVE`; default mock PPP feeds real ranking scores, stamped
  `SourceType.COMTRADE` (`providers/market_enrichment/mock.py:35`).
- **Observed prices:** live SerpApi path is real, deepen-gated, and correctly keyed
  (08-06 critical #6 fixed). Keyless, the mock **fabricates** prices with invented
  competitors and `listings.example` URLs, persists them, and renders them in the
  executive docx — no fail-closed gate analogous to sending (§5 C3).
- **Reports:** the Wave-3 Executive Multi-Market Report is a real renderer (RTL docx,
  per-figure source labels, declared-gap lines, provenance footer) — not template
  stuffing. Two honesty gaps: demo-seed rankings are labeled "UN Comtrade" in the
  exec report (`ranking.py:76` hardcodes `source="world_trade"`, label map upgrades
  it), and the buyer `is_demo` flag is computed and tested in `report_view.py` but
  dropped at the render seam — never shown.

### 4.3 Buyer discovery → campaigns → email — **PARTIAL**
- **Discovery:** pipeline complete (customs → maps long-tail → enrichment → email
  waterfall → scoring), but the shipments provider is **always mock**
  (`registry.py:50-60` returns `MockShipmentsProvider` unconditionally) and all live
  discovery adapters are self-documented as unproven. The task is fire-and-forget: no
  retry, no persisted failure state, nothing for the UI to poll to terminal (§6 H3).
- **Drafting:** complete — per-draft commit idempotency, compliance footer (identity +
  postal address + unsubscribe) force-appended *after* the LLM, buyer-language drafting
  (verified live in the golden path: Hindi draft for an Indian buyer).
- **Approval gate:** complete and the best-engineered part of the system — state
  machine + worker re-check under row lock + DB CHECK constraint, verified live.
- **Send:** mailbox OAuth path (Gmail/Microsoft) code-complete including token refresh,
  reauth pause/resume, NDR bounce parsing, 5% bounce / 0.1% complaint auto-pause —
  all hermetic-proven only. **Smartlead is scaffolding behind an honest gate**: the
  adapter posts to `/campaigns/{our-internal-uuid}/leads` (no Smartlead-campaign-id
  mapping exists anywhere), `register_webhook_events()` is a no-op, and the webhook
  schema only matches the in-repo mock. Correctly fail-closed via
  `SMARTLEAD_SEQUENCE_VERIFIED`, but the advertised cold-email infrastructure is not
  deliverable through Smartlead today.
- **The biggest send-path hole:** worker-side `SendBlocked` (daily cap, disconnected
  mailbox, transient provider rejection) strands emails in `queued` **forever** — the
  only dispatch site is the queue route; no beat drains `queued`; the queue-time gate
  checks *factory* counters while sends increment *account* counters, so the cap is
  enforced only where blocking strands mail (§5 C4). Disconnecting a mailbox doesn't
  pause its campaigns.
- **Tracking:** replies + bounces real on both channels; **opens are webhook-only and
  only the mock emits webhooks** — production open-rate will read ~0% and look broken.
  No click tracking. Follow-up drafts copy the parent's `body_html` verbatim (intro
  only in `body_text`) and embed the parent's unsubscribe token.

### 4.4 Ad campaigns — **ABSENT**
No model, route, provider, or stub anywhere in the repo. "Campaigns" means cold-email
outreach only. If marketing claims ad campaigns, the claim has zero backing; remove or
re-scope it before launch.

### 4.5 Web UI (button-by-button) — **PARTIAL: fully wired, weak on errors**
Every `api.*` call in `apps/web/src` maps to a real FastAPI endpoint with the right
method — no dead buttons, no TODO handlers, no phantom endpoints; locale parity is
machine-checked (362/362). The inverse problems are real:
- API errors render as **empty states** (`useApi.ts` exposes `error`; dashboard,
  campaigns, buyers, inbox pages ignore it — a 500 looks like "you have no campaigns");
  several buttons swallow rejections silently (draft, create-campaign, discover, warmup).
- Backend capabilities with no UI: `POST /campaigns/{id}/activate` (campaign status is
  decorative; the hourly health sweep scans only `active` campaigns → inert),
  outcome reporting, and the **entire notifications API** — so "send interrupted" /
  "reconnect your mailbox" / "new reply" alerts are invisible in-app.
- Login form ships prefilled demo credentials (`login/page.tsx:11-12`).
- The buyers page polls an unpaginated N+1 endpoint every 4 s with no terminal state.

---

## 5. Critical blockers — must fix before launch

| # | Blocker | Anchor | Size |
|---|---|---|---|
| C1 | **Make the world-trade sync runnable from the shipped artifact.** `sync_world_trade` ImportErrors forever (`etl` not in image, `apps/api/Dockerfile`; `workers/tasks.py:733`) and `COMTRADE_OFFLINE=1` is the deployed default (`deploy-to-railway.sh:283`). Ship `etl/` in the worker image (or a dedicated etl service), flip the default, and run **one verified live Comtrade sync** (`world_trade_sync.py:212` is explicitly marked unverified). Until then the headline feature is a permanent failure loop. | `Dockerfile`, `tasks.py:733`, `deploy-to-railway.sh:283` | days |
| C2 | **Fix the deploy storage default.** `deploy-to-railway.sh:279` ships `STORAGE_BACKEND=local` across four containers: vision silently degrades to text-only AND executive report downloads 404 (worker writes its disk, API reads its own — `tasks.py:505-511` vs the download route). Set S3 + `REQUIRE_OBJECT_STORAGE=1` in the script, or make it refuse to proceed. | `deploy-to-railway.sh:262-283`, `storage.py:99-112` | hours |
| C3 | **Fail-close the mock data providers outside `local`, like sending already does.** Keyless prod persists fabricated observed prices into the client-facing docx (`providers/pricing/mock.py`, rendered at `silk_reports.py:4053`) and stamps mock enrichment as `COMTRADE` (`market_enrichment/mock.py:35`). Same `GatedSendingProvider` pattern, one class each. | `registry.py:92-127` | hours |
| C4 | **Own every non-terminal email state.** Drain/redispatch or surface `SendBlocked`-stranded `queued` emails (`tasks.py:564-568`, `sending.py:151-156`); reconcile the factory-counter vs account-counter gate mismatch (`approval.py:163-165` vs `sending.py:164-167`); pause campaigns on mailbox disconnect (`api/sender_accounts.py:71-93`). | see anchors | days |
| C5 | **Run the live-smoke lane and one real pilot campaign before launch.** Comtrade, Gmail/Microsoft send, real NDR bounces, SerpApi prices, vision-over-S3 — all exist in code, none ever proven. The launch gate proposed on 08-06 is still unmet; `live-smoke.yml` has never been dispatched. | `.github/workflows/live-smoke.yml` | days (mostly waiting on keys) |
| C6 | **Neutralize the legacy engine deployment surface.** `packages/silk_intel/silk_intel/api.py` runs open-by-default when `SILK_API_KEY` is unset and ships its own `railway.json` (`startCommand: uvicorn api:app`) + `Dockerfile` + `netlify.toml` inviting exactly that deploy; `silk_platform` includes hand-rolled crypto. Delete the deploy artifacts, make the key mandatory outside local, and confirm launch topology is body-only. | `api.py:113-119`, engine `railway.json` | hours |
| C7 | **Align product claims with the code.** "Ad campaigns" doesn't exist; "screen every world market" is a 14-country demo seed; opens/clicks aren't tracked on the production path. Fix the copy or build the features — shipping the gap is a trust breaker with real clients. | — | hours (copy) |

## 6. High-priority (fix before or immediately after launch)

- **H1 Demo-data honesty:** surface `coverage_state == "demo"` in the schema/UI and
  stop rendering demo rankings as "UN Comtrade" (`ranking.py:76`,
  `silk_reports.py:172-179`); render the computed-but-dropped buyer `is_demo` flag
  (`silk_render.py:2094-2106`).
- **H2 Blocking I/O in `async def` handlers** stalls the single-process event loop under
  concurrent uploads/webhook bursts (`api/products.py:59-123`, `api/webhooks.py:61-83`;
  one uvicorn worker, `start-api.sh:89`). Make them sync `def` (threadpool) or async-safe.
- **H3 Buyers page + discovery:** unpaginated N+1 list polled every 4 s forever
  (`buyers.py:85-113`, `useApi` 4000 ms) with no discovery status row to settle on —
  ~220-buyer market × 10 open tabs ≈ 550 queries/s. Add a discovery-run state, pagination,
  contact join, poll backoff/stop.
- **H4 Observability floor:** nothing scrapes `/metrics` (HTTP-only metrics anyway — no
  queue depth, task failures, beat liveness), `SENTRY_DSN` unset by the deploy script,
  no Railway `healthcheckPath`, beat death silently disables follow-ups, reply polling,
  warmup, **and all three reapers**. Add queue/beat gauges + a beat-liveness canary in
  `/health` + alerting.
- **H5 Gmail MIME header injection:** `mime["Subject"]`/`From`/`To` set from
  user-editable strings with no CRLF sanitization (`gmail_oauth.py:182-196`); subject
  allows newlines (`campaigns.py:182`). Strip/reject CR/LF (the Graph path is safe).
- **H6 UI error honesty:** render `useApi.error` everywhere it's ignored; add `.catch`
  to the silent buttons; wire the notifications API into the shell.
- **H7 Unsafe production defaults:** `TRUSTED_PROXY_COUNT=0` (login throttle collapses
  to a global bucket → 20 junk POSTs lock everyone out if the deploy script isn't used)
  and `api_base_url=http://localhost:8000` (missed `API_BASE_URL` ⇒ localhost
  unsubscribe links in real mail). Fail startup outside `local` like `SECRET_KEY` does.
- **H8 RFC 8058 on Microsoft:** Graph adapter omits `List-Unsubscribe-Post`
  (`microsoft_oauth.py:132-135`) — with the (correctly) POST-only `/u` route, Gmail/Yahoo
  one-click unsubscribe won't work for Microsoft-sent mail.

## 7. Important improvements (medium)

1. Follow-up drafts: regenerate `body_html` with the intro + new token (`tasks.py:622-630`); localize beyond English; make cadence/count configurable.
2. Engine SQLite spend-cap/cache is per-container and reset on redeploy — the paid-call cap is soft in prod (`silk_store.py:34-44`); mount a volume or move counters to Redis/Postgres.
3. Alembic on every boot with no lock — two replicas or a crash-restart race concurrent `upgrade head` (`start-api.sh:53`); take a Postgres advisory lock.
4. DB pool sizing (default 5+10) vs 40-thread pool + polling workload (`db.py:15-19`); tune pool + add indexes for reconciler scans.
5. Redis persistence unspecified on Railway; restart loses queued tasks (50-min recovery UX), rate-limit windows, and the jti denylist (fail-open). Document/configure AOF; consider fail-closed revocation for admin routes.
6. Unbounded per-contact LLM drafting with no cap/failure surfacing (`email_drafting.py:172-212`); no Anthropic prompt caching or adapter retry.
7. No DB uniqueness for (campaign, contact, followup_number) — concurrent drafting can duplicate outreach.
8. `Email.is_approved` requires `approved_by` while the CHECK was re-keyed to `approved_at` — erasing an approver's user row blocks their queued sends (`models/email.py:38-50,117-119`).
9. Throttle `/auth/register`; add Origin/Sec-Fetch-Site validation on cookie-authed mutations; gate `/docs` + `/metrics` in prod.
10. Pagination on `/products` and admin lists; SQL-side dashboard aggregation.
11. E2E gap: all 35 Playwright specs are fully route-mocked — add one non-mocked lane (real FastAPI + eager Celery + mock providers; the stack boots offline) and a CI contract check of web calls vs the OpenAPI dump.
12. Celery: `--max-tasks-per-child`, documented SIGTERM drain (routine deploys currently manufacture "send interrupted" cancellations).

## 8. Nice-to-haves

Repo hygiene (move the now-four root audit files to `docs/audits/`; delete engine
`netlify.toml`/`railway.json`/`fix_agent.py`/legacy `web/`; merge duplicate deploy
scripts) · slim the prod image (engine tests/samples/web out via `.dockerignore` +
build guard; Next standalone output) · engine packaging (real `silk_intel.` namespace;
stop adding source-text tests; decompose god-files opportunistically; `print()`→logging;
ruff T201 lane) · pin base images · Terraform: finish or delete · click tracking or open
descope · consume `HSCorrection` for classifier improvement · poll backoff · update the
engine's vendored `CLAUDE.md` to defer to the monorepo law.

## 9. What is genuinely good (keep doing this)

- The verification culture is top-decile and **real**: 2,569 hermetic engine tests +
  ~90 API test files + 35 e2e specs, all green when actually run; invariant lock tests;
  AST guards; migration-linearity tests born from a real incident (PR #86).
- The approval/suppression/two-phase-send core would pass most professional security
  reviews: triple-enforced human gate, at-most-once semantics with an honest reaper,
  suppression at egress, fail-closed sending, encrypted tokens, full audit trail.
- Security posture overall (7.5/10): fail-closed config, consistent tenant scoping on
  every object route, pinned JWT alg + jti revocation, autoescaped rendering, per-request
  CSP nonce, non-root containers, no committed secrets, prod-guarded demo seeds.
- Honest-provenance design (DataPoint envelopes, declared gaps, fixture downgrades) —
  the violations in §5 C3 stand out precisely because the rest of the system is honest.
- The remediation loop demonstrably works: 7 of 9 criticals closed in five days with
  test locks. Aim it at the live path next.

## 10. Suggested structural investments

1. **A "deploy-config lock" test family** — assert the deploy scripts never emit
   `STORAGE_BACKEND=local` without `REQUIRE_OBJECT_STORAGE`, never omit
   `TRUSTED_PROXY_COUNT`/`API_BASE_URL`/`SENTRY_DSN` (C2/H7 are grep-detectable).
2. **A terminal-state contract**: every `.delay()` reachable from a 202 endpoint must
   write a pollable terminal state or be explicitly registered fire-and-forget —
   generalizes the products/analyses fix that discovery missed.
3. **An engine-import allow-list lock test** for the 7-module body→brain seam (clean by
   discipline only today), plus an async-handler AST guard (H2's class).
4. **A scheduled full-stack smoke** (web → api → worker → Postgres, mock providers) and
   the live-smoke dispatch as a standing launch/regression gate once keys exist.
5. **Decide deep research**: the engine's 12-mission `/research` + PDF pipeline — the
   repo's most mature asset — is still unreachable from the product and undecided.
   Bridge it (worker + adapter, HS-resolve pattern) or descope it in an ADR.

## 11. Closing assessment

The gap between this codebase's process quality and its launch readiness remains the
story. Everything a disciplined team can prove offline has been proven offline —
including, in this audit, a full golden-path run against a real database and a real
HTTP boot. What has never been proven is the product's actual job with actual data:
the shipped artifact cannot sync world-trade data at all, the scripted deploy breaks
images and report downloads, keyless mode fabricates client-facing prices, and no email
has ever been sent through a real provider. The nine-blocker list from 08-06 was
largely burned down in five days, which is why this list is credible as a launch plan
rather than a graveyard: C1–C7 above are each hours-to-days, and the team's own
remediation velocity is the best evidence they'll get closed. Fix the deploy seam,
fail-close the remaining mocks, run one real pilot campaign end to end, and this is a
launchable 8/10. Ship it as-is and the first real customer's first real product will
hit C1 within the hour.

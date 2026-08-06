# Repository Audit — Silk United (Pre-Launch Comprehensive Review)

**Date:** 2026-08-06 · **Type:** read-only pre-launch audit (no business logic changed) ·
**Baseline:** HEAD `1b48f01` (post-PR #83) · **Follow-up to:** `CODE_AUDIT_2026-08-05.md`

**Method:** nine parallel read-only dimension passes (architecture & code quality ·
HS-classification feature · market-analysis feature · outreach/campaign feature ·
backend security · web security · reliability & production readiness · performance ·
prior-audit delta), each followed by an independent adversarial verification pass that
re-read every cited location and tried to refute each critical/high finding. In parallel,
the full offline verification suite was actually executed (results in §2). Findings below
are anchored to `file:line` at HEAD. No paid or live APIs were called; no `.env` contents
were read; secret values are never reproduced.

---

## 1. Executive summary — readiness score: **6 / 10**

This is two different platforms wearing one repo. As a piece of *engineering process*,
it is well above average: 2,881 tests all green (actually run for this audit, not
claimed), clean layering in `apps/api`, executable architecture decisions (AST guard
tests, invariant tests, ADRs that admit deviations), and a demonstrated remediation
loop — of the 2026-08-05 audit's 19 tracked Critical/High/Medium findings, **9 are fully
fixed, 6 partially fixed, 4 still open** (§9). The human-approval gate on outbound email
is genuinely enforced in three independent layers (API state machine, worker row-lock
re-check, DB CHECK constraint), not just in the UI.

As a *launch candidate*, it is not ready. The dominant pattern — and the reason the
score is not higher — is that **nearly everything is complete and test-locked against
deterministic mocks, while the live paths that launch actually depends on are unproven,
misconfigured, or missing**:

- The headline promise ("screen every world market") runs on a **14-country × 6-HS demo
  seed**; the live data sync is manual, unscheduled, and its API entry point is marked
  unverified in the code itself (§5.2).
- Every outbound email carries an **unsubscribe link that 404s** — the web origin has no
  `/u` route (§6.1). This is a legal/compliance breaker on the money path.
- The production send path (connected Gmail/Microsoft mailboxes) has **no bounce
  detection**, so the 5% bounce auto-pause — the domain-reputation guardrail — can never
  fire (§5.4).
- An approved email can be **sent twice** after a worker crash or Redis redelivery; an
  OOM-killed task is silently lost with no reaper (§7).
- On the documented default deploy topology, the uploaded product image **never reaches
  the vision model** — it silently degrades to text-only classification (§5.1).
- Any transient LLM failure **permanently strands** a product or analysis in `pending`
  with the UI polling forever; there is no retry, no failed state, no operator signal (§7).
- 20 junk POSTs per 5 minutes **lock every user out of login** — the per-IP throttle is
  keyed on the proxy's IP in the deployed topology (§6.2).

None of these is architecturally hard to fix; most are days, not weeks. But every one of
them bites *the moment real users, real data, and real keys arrive* — which is precisely
the launch event. The score decomposes to roughly: engineering discipline 8.5/10,
mock-mode product completeness 8/10, live-path readiness 3/10, operations readiness 4/10.

### Severity totals (this audit, post-verification, deduplicated)

| Severity | Count | Theme |
|---|---|---|
| Critical (launch blockers) | 8 | dead unsubscribe · no bounce detection · double-send/lost-task · demo-seed screening · broken live prices · image never analyzed · no pipeline error recovery · login lockout DoS |
| High | 7 | CI gating hole · silk_platform in prod image · buyer-discovery O(n) · unbounded LLM drafting · followup N+1 sweep · no metrics/alerting · Smartlead webhooks unwired |
| Medium | ~24 | session revocation · crypto degradation · CSP/Next CVE · reflected XSS · pool math · ephemeral storage · provenance synthesis · migration drift · report gaps |
| Low/Info | ~25 | hygiene, doc drift, dead code, pinning |

Every severity above reflects the adversarial verification pass, which confirmed all 8
critical items at HEAD and downgraded 6 findings the first-pass auditors had over-rated.

---

## 2. Verification evidence (actually executed)

All suites were run for this audit at HEAD `1b48f01`; working tree confirmed clean afterwards.

| Suite | Result |
|---|---|
| `tools/check_no_pandas.py` (I7) | PASS — exit 0 |
| `tools/harness_verify.py` | PASS — exit 0, no network calls |
| `packages/contracts` pytest | **9 passed** |
| `apps/api` ruff check + format | clean |
| `apps/api` pytest (real Postgres 16 + pgvector + Redis) | **327 passed, 0 failed, 0 skipped** (135s) |
| Engine hermetic suite (`packages/silk_intel/silk_intel`) | **2,545 passed, 0 failed, 21 skipped** (347s) — all 21 skips env-gated opt-in lanes (13× `SILK_RUN_E2E`, 2× `SILK_RUN_LIVE`, 6× missing soffice/pymupdf/fonts) |
| `apps/web` pnpm lint | clean |
| `apps/web` tsc typecheck | clean |
| `apps/web` build | skipped (lint+typecheck cover static verification) |

The test estate is a real strength — but note what it proves: hermetic/mock behavior.
No live vendor path (Comtrade sync, Serper/SerpApi prices, Smartlead, Gmail/Microsoft
send, Anthropic vision) is exercised by any green lane, and several of the critical
findings below live exactly in that untested gap.

---

## 3. Architecture & code quality

**Verdict: strong shell, heavy vendored core. No launch blockers on this axis.**

Strengths (verified, not aspirational):

- `apps/api` (~15k LoC) is cleanly layered: thin routers → services → providers. Celery
  tasks all go through services, open their own sessions, and re-establish context from
  explicit payload flags (`app/workers/tasks.py`). Zero bare `except:`; all 19 broad
  excepts either re-raise after cleanup or degrade a volatile provider to a logged note.
- The brain/body seam is narrow and adapter-mediated: the product imports only 9 engine
  modules, mostly via `app/services/engine.py`; live Comtrade calls route through the
  engine's hardened data layer (throttling/circuit-breaker/cache) instead of duplicating it.
- Decisions are executable: `apps/api/tests/test_no_silk_platform_import.py` (AST guard),
  `tools/check_no_pandas.py` (I7), the contracts suite. ADR-0002/0003/0004 honestly record
  real deviations instead of papering over them.
- `packages/contracts` (147 LoC, zero deps, frozen dataclass, both bridges consumed) is a
  model shared kernel. The web app is small, pattern-consistent, and talks only to the API.
- Prior-audit H-5 ("three backends reimplement the spine") is substantially remediated:
  Stage-1 scoring delegates to `silk_market_ranker.stage1_screen_score`
  (`app/services/world_funnel.py`), and the Word report derives from the engine's canonical
  `build_view → render_docx` path.

Weaknesses:

- **[HIGH] The full `silk_platform` legacy product ships inside the production image.**
  28 modules / 5,680 LoC of parallel auth, billing/wallet, prospects, and a cold-send
  queue **with no per-email approval gate** (`silk_platform/api.py:820` →
  `email_queue.py` → `smtp_transport.py`; ADR-0004 itself calls it "the one in-repo send
  path outside the I3 state machine"). `apps/api/Dockerfile` copies `packages/` wholesale,
  so the only barriers between production and an unapproved send pipeline are one AST
  guard test and entrypoint discipline. "Locked out by a repo test" is far weaker than
  "not shipped." Exclude it (and the engine's `tests/`, `docs/`, `samples/`, `web/`) from
  the built artifact, and put a date on the ADR-0004 retirement.
- The engine's `api.py` is a ~3,200-line `create_app()` god-function with 34 nested route
  closures (`packages/silk_intel/silk_intel/api.py:143`). Maintained only by vendored-repo
  discipline.
- Error-handling quality is bimodal: the engine carries ~300 `except Exception`, **39
  `except Exception: pass`** (including data-layer paths), and ~124 `print()` calls vs
  the product's structlog discipline. A materially lower observability floor for the code
  that does the heaviest work.
- Doc drift feeds the agent harness: `docs/ENGINE_ARCHITECTURE.md`'s "real measured
  numbers" are ~80% stale (claims api.py at 1,528 lines/25 routes vs actual 3,355/34), and
  the engine `CLAUDE.md` references a Streamlit `app.py` that does not exist. The harness
  instructs agents to read these before changing code.
- `app/services/report_view.py:46` **fabricates a uniform confidence of 0.9** when
  reconstituting engine DataPoints — provenance theater in a codebase whose central ethos
  is "every number carries its source" (see also §5.3).
- Minor: dead vendored deploy artifacts (`netlify.toml`, `railway.json` inside the engine),
  orphan `fix_agent.py`, 90KB of prior audit reports at root, deploy logic duplicated
  across two 335-line shell/PowerShell scripts, `api/reports.py` bypassing the engine
  adapter layer.

---

## 4. Feature readiness — HS classification (product intake)

**Verdict: PARTIAL. Mock path complete and honest; live path silently degraded and brittle.**

| Sub-feature | Status |
|---|---|
| Image upload | Partial |
| HS classification (mock/offline) | **Complete** — deterministic, honest (mock explicitly ignores image bytes), real 5,628-row HS6 seed, no-fabrication contract (score<0.7 → None) |
| HS classification (live) | Partial — vision description is real with a key; the HS *proposal* is never live (CSV+difflib only; the engine's Claude HS classifier and its cache are entirely unwired from the product) |
| HS confirmation flow | Partial — backend complete & invariant-locked; UI dead-ends on failure |
| Downstream use of confirmed HS | **Complete** — 409-gated everywhere, worker re-checks, load-bearing |

Critical findings (all adversarially confirmed):

1. **[CRITICAL] The uploaded image never reaches the vision pass on the documented
   default deploy topology.** `LocalStorage.put` returns a `file://` URL on the API
   container's filesystem (`app/services/storage.py:25-29`); the worker is a separate
   container with no shared volume; `_load_image` silently returns `(None, 'image/jpeg')`
   on a missing file (`app/services/product_vision.py:51-59`) and classification proceeds
   text-only with **no note, no log, no declared gap**. `STORAGE_BACKEND` defaults to
   `local` (`app/config.py:44`) and both Railway deploy scripts hard-set it
   (`deploy-to-railway.sh:261`, `.ps1:278`). The headline feature — photo → HS code —
   quietly doesn't use the photo in production. Fix: persist the storage *key*, fetch
   bytes through the storage interface in the worker, fail loudly or record a declared-gap
   note, default multi-container deploys to S3, and remove the silent S3→local fallback
   (`storage.py:72-77`).
2. **[CRITICAL] Intake task has no error handling or retry.** `process_product_intake`
   (`app/workers/tasks.py:106-145`) wraps nothing; the Anthropic adapter raises on any
   non-2xx (`providers/llm/anthropic.py:40`); on exception the product stays `pending`
   forever and two UI pages poll every 2s indefinitely (`products/[id]/page.tsx:16-25`).
   Routine 429s at launch = permanently stranded products. (Same pattern for all three
   analysis-pipeline tasks — §7.)
3. **[CRITICAL] Failed classification dead-ends the entire funnel in the UI.** On
   `classification_status='failed'` the card renders an empty list with a permanently
   disabled Confirm button (`HsSuggestionCard.tsx:31,58-64`); no failed-state copy exists
   in either locale; there is **no manual HS search/entry UI** even though the backend
   fully supports it (`GET /hs-codes/search` has zero web references;
   `PUT /products/{id}/hs-code` exists). Every downstream step is 409-gated on a confirmed
   code, so a strict-resolver miss (deliberate: `silk_hs_resolver.py:163-167`) blocks the
   user from the entire product with no recovery path.

Also noteworthy: S3 backend persists an *expiring presigned URL* as `product.image_url`
(`storage.py:60`); zero test coverage of the actual upload leg; the `HSCorrection`
feedback loop is write-only (recorded, never consumed).

---

## 5. Feature readiness — market analysis, prices, reports

**Verdict: PARTIAL. Real pipeline code, tested — sitting on demo data, with the live
price path structurally broken and the engine's best asset unreachable.**

| Sub-feature | Status |
|---|---|
| World screening / top-5 ranking | Partial — pipeline real & tested; data demo-only |
| Per-country competitor analysis | Partial — real Comtrade math; offline fixtures cover demo pairs only |
| Observed prices | **Scaffolding** — mock fabricates listings; live path cannot work as wired |
| Data-source coverage | Partial — engine adapters genuinely live/keyless (Comtrade, World Bank, Eurostat, FAOSTAT, GDELT, News, Trends); product-side live switches undocumented |
| Research report + PDF | Partial — JSON/HTML/docx real; **no PDF endpoint in the product**; deep-research pipeline unreachable |
| Provenance guarantees | Partial — engine structurally complete; product bridge synthesizes confidence |

Confirmed findings:

1. **[CRITICAL] "Screen every world market" runs on a 14-country × 6-HS demo seed.**
   `screen_world` returns an empty shortlist when `world_trade` has no rows for the HS6
   (`app/services/world_funnel.py:103-105`); the only shipped population is the demo seed
   (`app/seeds/seed.py:230-274`, `source='UN Comtrade (demo seed)'`). The live ETL
   requires manual `--hs6` invocation ("full-scope batch is TODO",
   `etl/world_trade_sync.py:172-175`), carries an in-code warning that the
   `comtradeapicall` entry point is **unverified against the live API**
   (`world_trade_sync.py:206-208`), and no beat entry refreshes it. Any real customer
   product outside the 6 demo codes gets an empty or demo-data funnel. This is the single
   largest gap between the pitch and the code. Fix: verify the entry point once (free),
   add on-demand per-HS6 sync at HS-confirmation time + a scheduled refresh, and surface
   a loud declared gap in the UI when coverage is missing.
2. **[CRITICAL] The live observed-prices path is structurally broken twice over.** The
   registry selects the live provider on `SERPER_API_KEY` (`providers/registry.py:81-87`)
   but the engine agent requires `LOCALPRICE_API_KEY` — a *different vendor's* key
   (SerpApi) — and returns a declared-gap None without it
   (`silk_localprice_agent.py:102-107`); `config.py:63-66` admits the adapter never passes
   it. And the shopping query sent is the **raw HS6 code string**, not the product name
   (`providers/pricing/localprice.py:66`). Neither key appears in `.env.example`. The
   live feature has plausibly never produced a real price. Fix: key the registry on the
   key the agent reads (or map explicitly), pass the product name through the protocol,
   document both keys.
3. **[HIGH] The deep-research pipeline — the strongest asset in the repo — is not part
   of the product.** The 12-mission research, quality gate, AI judge, and all PDF
   renderers exist only behind the vendored engine's own `api.py`; `grep research`
   across `apps/` returns zero matches, and the product has **no PDF export at all**
   (`apps/api/app/api/reports.py:142-214` serves JSON/HTML/docx only). ~2,500 tests
   protect a feature customers can't reach. Decide explicitly: bridge it through a worker
   (like HS-resolve was bridged) or descope it from the launch story in the docs.
4. **[MEDIUM]** Stage-2/3 enrichment results never reach the customer-facing report
   (`report_view.py:113-141`); the product's top-5 uses a simpler volume/growth/tariff/PPP
   heuristic, not the engine's weighted 4-component ranker (`services/stage2.py:28`);
   `report_view.py:45` stamps constant `confidence=0.9` / `retrieved_at=None` on every
   figure — synthesized provenance on the flagship "every number carries its source" claim;
   the mock market-enrichment stamps fabricated tariff/PPP as `SourceType.COMTRADE`
   (`market_enrichment/mock.py:35`).

---

## 6. Feature readiness — outreach, campaigns, sending (and "ad campaigns")

**Verdict: the strongest feature area on mocks — approval, suppression, warm-up, replies
are genuinely done — with three production-path holes that gut tracking and compliance.**

First, scope clarification: **there is no paid/social ad-campaign feature anywhere in the
repo, and none is specified** — "campaigns" means cold-email outreach only
(`docs/MASTER_PROMPT.md:9-17`). Report to stakeholders as by-design absence, not a gap.

| Sub-feature | Status |
|---|---|
| Verified buyer-list building | **Complete** (on mocks; live adapters exist behind same interfaces, unproven) |
| Campaign creation (model/routes/UI) | **Complete** |
| AI drafting in buyer's language | **Complete** (compliance footer force-appended post-LLM) |
| Human approval gate (server-side) | **Complete** — 3 independent layers, bypass-tested |
| Unified replies inbox | **Complete** (metadata-only by documented design) |
| Unsubscribe / suppression machinery | **Complete** — but see §6.1: the *link itself* is dead |
| Rate/volume limits (warm-up ramps) | **Complete** |
| Sending providers | Partial — mailbox OAuth adapters complete-looking but never live-proven; Smartlead correctly fail-closed (PR #83) yet unusable even if un-gated |
| Send tracking (opens/clicks/replies) | Partial — replies real; opens webhook-only (mock-only in practice); clicks absent |
| Bounce handling | Partial — webhook path complete; production mailbox path has zero detection |
| Campaign dashboard | Partial — fed almost entirely by mock-generated events today |

Confirmed findings:

1. **[CRITICAL] Every outbound email's unsubscribe link 404s.** `unsubscribe_url()`
   builds `{app_base_url}/u/{token}` (`app/services/email_drafting.py:41-43`) —
   `APP_BASE_URL` is the **web** origin in every production config
   (`deploy-to-railway.sh:259`, `.ps1:276`, `docs/DEPLOY_RAILWAY.md:176`) — but the
   `/u/{token}` handlers live only on the FastAPI root (`app/api/public.py:60-75`), and
   the web app proxies only `/api/v1/*` (`apps/web/next.config.ts:50`) with no `/u`
   route. A recipient clicking unsubscribe gets locale-redirected to `/ar/u/{token}` and
   a 404. The same URL feeds the RFC 8058 `List-Unsubscribe` headers in both live mailbox
   adapters (`gmail_oauth.py:186-187`, `microsoft_oauth.py:132`) — which the Smartlead
   fail-closed gate does **not** cover. Dead opt-out on the cold-email money path =
   CAN-SPAM/PDPL exposure, spam complaints, and domain damage from day one. Fix: build
   the URL from `api_base_url`, or add a Next rewrite for `/u/:token` (GET **and** POST);
   add an integration test resolving the generated URL against the deployed routing
   table. If proxying via web, fix the reflected-XSS below first.
2. **[CRITICAL] No bounce detection on the connected-mailbox path — the primary
   production send path.** Reply polling matches by the *contact's* address
   (`app/services/replies.py:41-44`), so mailer-daemon/postmaster NDRs can never match;
   neither OAuth adapter parses failures (grep: zero hits). Bounce counters, auto-
   suppression, and the 5% bounce auto-pause (`deliverability.py:95-99`) only advance via
   the Smartlead-shaped webhook that **only the in-repo mock emits**. Every product-flow
   campaign hard-requires a mailbox (`api/campaigns.py:62-67`), so in production:
   `bounced_count` stays 0 forever, dead addresses keep receiving follow-ups, and the
   domain-reputation guardrail is inert. Fix: parse NDRs in `fetch_replies` (Gmail
   mailer-daemon + `X-Failed-Recipients`; Graph `REPORT.IPM.Note.NDR`), route through
   `record_engagement('bounced')`, with a hermetic synthetic-NDR test.
3. **[HIGH] Smartlead engagement webhooks are unwired end-to-end.** The endpoint
   validates a bespoke schema only the mock emits (`schemas/campaign.py:86-89`;
   `providers/sending/mock.py:84-109` even signs with the bespoke header);
   `register_webhook_events()` is an explicit no-op (`smartlead.py:145-148`); matching
   uses a `provider_message_id` the adapter itself labels UNPROVEN. If Smartlead is ever
   un-gated, all tracking silently stops. Extend the PR #83 gate so cold-send stays
   closed until webhook delivery is also verified.
4. **[MEDIUM]** No open tracking on the mailbox path (dashboard open-rate ≈ 0 in
   production, `email_drafting.py:224`); follow-ups send stale `body_html`
   (`workers/tasks.py:369`); `/activate` never called by the UI so campaign statuses are
   partly decorative (`tasks.py:388`); **silent mock-sender fallback in production** when
   a campaign loses its sender account (`tasks.py:317`) — a compliance-grade bug that
   would mark emails "sent" that went nowhere; reply/reauth notifications have no UI.

---

## 7. Reliability & production readiness

**Verdict: the weakest axis relative to how good the tests look. The system has no
recovery story for its own failure modes and no operational visibility.**

Confirmed findings:

1. **[CRITICAL] Approved emails can double-send.** `provider.send()` fires while the row
   is still `queued` in an uncommitted transaction (`app/services/sending.py:137-144`,
   commit only at task end); `task_acks_late=True` on Redis with the default 3600s
   visibility timeout and no claim state (`EmailStatus` has no `sending` member; no
   `claimed_at` column) means a crash between provider-accept and commit — or any
   redelivery — re-sends. The row-lock only stops *concurrent* double-sends (and pins a
   DB connection across the vendor call). The engine's legacy queue solved exactly this
   (`migrations/platform/003_email_queue_claim_tracking.sql`) — the pattern exists
   in-repo but not on the live path. Fix: two-phase send (claim+commit before egress,
   sent+commit after), a beat reaper for stale `sending` rows, explicit
   `broker_transport_options.visibility_timeout`.
2. **[CRITICAL] Task loss and stranded state are silent and permanent.**
   `task_reject_on_worker_lost` unset → an OOM/SIGKILL'd task is consumed, not
   redelivered (`workers/celery_app.py:30-40`); no task anywhere declares retries; no
   time limits, so a hung vendor call blocks a prefetch-1 worker slot indefinitely; the
   beat schedule contains no reconciliation job; pipeline tasks never set
   `analysis.status='failed'` (grep-confirmed) and the approval state machine forbids
   re-queuing a stuck `queued` email. On Railway, OOM kills are a normal failure mode:
   a stuck-queued approved email is an invisible lost sale. Fix: failure transitions in
   every pipeline task, `autoretry_for` with backoff, global time limits, an hourly
   stuck-row reaper with operator notification.
3. **[HIGH] CI path-gating skips the API suite for changes to its own dependencies.**
   The `api` filter watches only `apps/api/**` (`.github/workflows/ci.yml:44-47`), yet
   `apps/api` has editable path-deps on `silk_intel` and `contracts` and imports engine
   modules in-process. An engine PR runs only the engine's hermetic lane; the integration
   seam the monorepo exists for is tested only *after* merge, on main. One-line fix.
4. **[MEDIUM]** No readiness gating anywhere (`/health` checks nothing; Railway configs
   declare no healthcheckPath); **no metrics, no alerting** — observability is structlog
   plus optional Sentry, and the prod image doesn't install `sentry-sdk`; default deploy
   writes uploads to ephemeral disk with a *silent* S3→local fallback
   (`storage.py:70-77`); tests run against `create_all` schema, never the
   alembic-migrated one — model↔migration drift is structurally unverified
   (`tests/conftest.py:60`); webhook engagement processing is not idempotent for
   bounce/complaint and has no replay protection; unbounded discovery fan-out
   (`api/buyers.py:50`); latent collision — the engine's `silk_store` keys Postgres mode
   off the same raw `DATABASE_URL` the product uses (`silk_store.py:47`); both
   live-integration lanes are undispatchable (vendored `live-smoke.yml`; product
   `live_smoke.py` wired to no workflow); beat is a SPOF with mutable file state on
   ephemeral disk; per-process in-memory rate limiting multiplies quotas across replicas.
5. **[LOW/INFO]** Base images and `uv` unpinned; web e2e runs entirely against
   hand-written mocks (no full-stack web→api→worker smoke exists anywhere); Terraform is
   a self-declared skeleton — Railway is the only real deploy target; deploy-time seed
   failure is soft (log-only).

---

## 8. Security

**Verdict: materially better than 2026-08-05 — the earlier criticals are fixed and
locked. What remains is one production-severe DoS, one compliance-severe web gap
(§6.1), and a tail of hardening debt. No hardcoded secrets found anywhere; only
local-dev defaults in code/compose. `.gitignore` correctly excludes `.env`; no tracked
credential files.**

Confirmed / notable:

1. **[CRITICAL] Login lockout DoS behind the deployment proxy.** `_client_ip()` returns
   `request.client.host` (`app/api/auth.py:41-42`), uvicorn is started with no
   `--proxy-headers`/`--forwarded-allow-ips` (`scripts/start-api.sh:32`), so behind
   Railway's edge every client shares the proxy's IP: `login:ip` at 20/5min
   (`auth.py:52`) means **any anonymous attacker sending 20 junk POSTs per 5 minutes
   429s every legitimate login** (same for both OTP limits). Correctly *not* spoofable —
   just wrong-keyed for the topology. Fix: trusted-proxy resolution + a regression test
   that distinct clients get distinct buckets.
2. **[MEDIUM]** No server-side session revocation — logout/password-change/admin-reset
   leave stolen 12h JWTs valid (`app/security.py:68`); login brute-force state is
   process-memory only (resets each deploy, per-worker); `TOKEN_ENCRYPTION_KEY` optional
   in production — mailbox OAuth token encryption silently degrades to
   `SHA256(SECRET_KEY)` (`app/crypto.py:47`); reflected XSS on the public unsubscribe
   confirmation page — raw token path param interpolated into HTML
   (`app/api/public.py:37`); production CSP still allows `unsafe-inline` scripts
   (`next.config.ts:17`); Next.js 15.2.9 predates the Aug-2025 patch line (middleware
   SSRF CVE-2025-57822, image-optimizer CVEs); the engine's standalone API still defaults
   auth-off with a key-writing settings endpoint if ever deployed as-is, and its
   `/research/readiness` remains unauthenticated with live-probe capability
   (`silk_intel/api.py:1958`) — moot only while the engine API stays undeployed.
3. **[LOW]** Unauthenticated `/auth/register` unthrottled (tenant spam + bcrypt burn);
   CSRF rests solely on `SameSite=Lax` (no Origin validation); OpenAPI docs (including
   admin surface) public in every environment; OTP has no production delivery channel —
   invites unsafe operator workarounds; demo credentials pre-filled in the production
   login bundle; `COOKIE_SECURE=0` escape hatch; API origin serves HTML with zero
   security headers; admin endpoints pass PII through query strings;
   `deploy-to-railway.sh --dry-run` still echoes generated secrets to stdout.
4. **[FIXED — verified]** Webhook signature fail-closed; Smartlead cold-send gate;
   SECRET_KEY fail-closed config + login-error surfacing; non-root containers; pgvector
   provisioning; audit-log immutability real in Postgres (engine's SQLite counterpart
   remains trivially droppable); first-admin bootstrap hardened (env-var password
   accepted — acceptable, documented).

---

## 9. Prior-audit delta (2026-08-05 → HEAD)

The last ten PRs were real work, honestly executed:

| Prior finding | Status at HEAD |
|---|---|
| C-1 release-gate suites unwired in CI | **FIXED** — root `e2e-live-shape.yml` runs rungs 2–3 + PDF acceptance |
| H-0 login loop (web missing SECRET_KEY) | **FIXED** — compose + deploy configs wire it |
| H-1 containers run as root | **FIXED** |
| H-2 Railway non-pgvector Postgres | **FIXED** |
| H-3 Smartlead cold-send unproven | Partial — fail-closed gate landed (PR #83); path itself still unproven; webhook wiring still absent (§6.3) |
| H-4 missing invariant tests | Partial — I4/I10 locked; I3 row-lock concurrency test still absent |
| H-5 three-backend duplication | Mostly fixed via documented-split (ADR-0003/0004 + lockout test) |
| H-6 unauth readiness + rate-limit bypass | Partial — limiter identity fixed; `/research/readiness` still unauthenticated |
| M-3 insecure secret default | **FIXED** (fail-closed) · M-5 audit-log **FIXED** · M-6 pagination **FIXED** · M-8 dockerignore **FIXED** |
| M-1 diagnostics paid-drain · M-2 CSP · M-4 platform throttle · M-9 unpinned images · M-11 token-in-body | Still open (M-1/M-11 documented owner decisions) |
| M-7 ephemeral storage | Partial — bash script warns; PowerShell still claims "nothing left to do" |
| M-10 CI soft-skip | Partial — PDF lane hard-runs; importorskip pattern remains |

---

## 10. Performance

**Verdict: fine at demo scale; several verified time bombs that grow with success.**

1. **[HIGH] Buyer discovery is O(entire country buyer table), not O(fetched leads).**
   Step 3 loads *every* buyer ever discovered in the country by any factory
   (`app/services/buyer_discovery.py:146`) and runs ~3 queries + scoring + a
   `ProductBuyerMatch` insert per row, plus rapidfuzz dedup that is
   O(candidates × country_buyers). At 8,000 DE buyers: ~30k query round-trips and ~1.6M
   fuzzy comparisons per discovery click, in one un-time-limited task. Scope step 3 to
   the buyers touched by this run; index-assisted dedup.
2. **[HIGH] Campaign drafting: one sequential LLM call per contact, unbounded, single
   commit at the end.** 300 contacts ≈ 10–25 min in one task; a restart at contact 299
   rolls back everything and `acks_late` re-runs — **paying for all 300 LLM calls
   again** (`email_drafting.py:194-210`, `tasks.py:271-281`). No prompt caching despite
   an identical repeated system prompt; no adapter retry. Commit per draft, cache the
   system block, chunk the task.
3. **[HIGH→grows] `process_followups` re-scans all historical sent mail hourly** with a
   per-row N+1 on unindexed `parent_email_id` (`tasks.py:344-359`; no index in any of
   the 14 alembic versions). Monotonically growing candidate set; will become the
   dominant DB load. Anti-join + index + window bound.
4. **[MEDIUM]** The two `async def` handlers (webhooks — the highest-frequency endpoint —
   and product upload) do sync DB/boto3 on the single event loop, including a fresh boto3
   client + `head_bucket` round-trip per upload (`api/webhooks.py:61`,
   `api/products.py:52`, `storage.py:51-77`); pool math: 40 threadpool slots vs default
   15-conn SQLAlchemy pool, one uvicorn process, no coordinated numbers anywhere
   (`db.py:15`, `start-api.sh:32`); unbounded list endpoints with per-row N+1s
   (buyers/campaigns); report rebuild does a per-buyer Contact query across all matches
   per request; `poll_replies` does sequential per-mailbox OAuth refresh in one beat
   task with a non-sargable match; single shared Celery queue with no rate/time limits —
   long tasks starve the send path; beat sweeps load whole tables into ORM objects and
   mutate row-by-row; Anthropic adapter builds a new HTTP client per call; engine spawns
   an unbounded daemon thread per async `/research`; frontend polls the full unpaginated
   products list every 2s; dashboard aggregates counters in Python.

---

## 11. Prioritized action plan

### (a) Critical — must fix before launch

| # | Blocker | Anchor | Rough size |
|---|---|---|---|
| 1 | Unsubscribe links 404 on the money path (+ fix the reflected XSS on the same page) | `email_drafting.py:41`, `next.config.ts:50`, `public.py:37` | hours |
| 2 | Bounce detection on the mailbox send path (NDR parsing → `record_engagement`) | `replies.py:37`, both OAuth adapters | days |
| 3 | Two-phase send + reaper + `visibility_timeout` (kill double-send & stuck-queued) | `sending.py:137`, `celery_app.py:30` | days |
| 4 | Pipeline error recovery: failure transitions, autoretry, time limits, UI terminal states, manual-HS fallback UI | `tasks.py:106-268`, `HsSuggestionCard.tsx` | days |
| 5 | Real `world_trade` data: verify comtradeapicall, on-demand per-HS6 sync at confirmation, scheduled refresh, loud declared gap | `etl/world_trade_sync.py:206`, `world_funnel.py:103` | days |
| 6 | Observed-prices live path: key the registry on the right key, query by product name, document keys | `registry.py:81`, `localprice.py:66` | hours |
| 7 | Image → worker: store keys not URLs, fetch via storage interface, S3 default for multi-container, no silent fallbacks | `product_vision.py:51`, `storage.py:25-77` | days |
| 8 | Proxy-aware client IP for auth throttles (+ regression test) | `auth.py:41`, `start-api.sh:32` | hours |
| 9 | CI: add `packages/silk_intel/**` + `packages/contracts/**` to the api filter | `ci.yml:44` | minutes |

Items 1–3 are all preconditions for the *first real send*; items 5–7 are preconditions
for the *first real analysis*. Treat "first live campaign for a pilot customer, end to
end, with real keys" as the launch gate and drive this list against it.

### (b) Important — fix soon after (or before, where cheap)

- Silence-kills class: remove the silent mock-sender fallback in production
  (`tasks.py:317`); alert on seed failure; alert on S3 fallback.
- Ops floor: `sentry-sdk` in the prod image; real `/health` (DB+Redis+broker) +
  Railway healthcheckPath; a `/metrics` endpoint (queue depths, send outcomes,
  stuck-row counts); stuck-row reconciliation beat (shared with (a)3/(a)4).
- Security hardening: Redis-backed rate limiting + login throttle (survives deploys,
  shared across workers); server-side session revocation (jti denylist); make
  `TOKEN_ENCRYPTION_KEY` required in production; Next.js patch-line upgrade; CSP nonce
  instead of `unsafe-inline`; Origin validation for cookie-authed mutations; throttle
  `/auth/register`; gate `/docs` in production.
- Image hygiene: exclude `silk_platform`, engine `tests/`, `docs/`, `samples/`, `web/`
  from the production artifact; pin base images; set a retirement date for ADR-0004.
- Correctness debt: run the API suite against alembic-migrated schema in CI; index
  `parent_email_id` (+ `sent_at`, `replied_at`); bound the followup sweep; per-draft
  commits + Anthropic prompt caching + adapter retry; scope buyer-discovery step 3;
  fix follow-up stale `body_html`; wire `/activate` or remove the status.
- Honesty debt: stop synthesizing `confidence=0.9` in `report_view.py`; carry real
  DataPoint confidence/retrieved_at through the bridge; don't stamp mock enrichment as
  `COMTRADE`; surface Stage-2/3 results in the report or label the gap.
- Decide the deep-research question: bridge `/research` + PDF into the product (worker
  + adapter, the HS-resolve pattern) or formally descope it from launch. Either answer
  is fine; the current in-between wastes the repo's best asset.
- Wire one dispatchable live-smoke lane (workflow_dispatch) that proves each vendor
  adapter once with real keys before launch — Smartlead webhook translator included if
  Smartlead is in scope.

### (c) Nice-to-haves

- Repo hygiene: drop the two root `CODE_AUDIT_*.md` into `docs/audits/`; merge the
  duplicate deploy scripts; delete `netlify.toml`/`railway.json`/`fix_agent.py` from the
  engine (with their guard-test updates, per BACKLOG); refresh
  `docs/ENGINE_ARCHITECTURE.md` numbers and the engine `CLAUDE.md`.
- Refactor the engine `api.py` god-function when it's next touched; reduce the 39
  `except Exception: pass` sites to logged degradations.
- Product polish: notifications UI; click tracking (or descope openly); follow-up
  localization beyond English; poll backoff + pagination in the products/dashboard
  pages; SQL-side dashboard aggregation; consume `HSCorrection` for classifier
  improvement; real `cost_per_unit` (BACKLOG item) for true margins.
- Terraform: finish it or delete it; a skeleton that looks real is worse than none.
- Full-stack e2e smoke (web→api→worker→Postgres) on a schedule, not just mocked
  Playwright.

---

## 12. Closing assessment

The uncomfortable truth: **this codebase is better at proving itself than at doing the
job.** The verification culture — invariant tests, AST guards, ADRs, hermetic suites,
fail-closed gates — is genuinely top-decile, and it has visibly compounded: the last ten
PRs closed most of the previous audit at speed, with fixes locked by tests. That same
culture, however, has been aimed almost entirely at the *mock* surface. The result is a
platform where the demo is bulletproof and the production path — real trade data, real
prices, real images, real sends, real bounces, real unsubscribes — is a string of
first-contact failures, several of them silent by construction.

The good news is symmetrical: because the architecture is sound and the seams are
narrow, every critical item above is a localized fix, and the team's own tooling (the
declared-gap ethos, the live-smoke scaffolding, the fail-closed gate pattern from PR
#83) is exactly the right machinery to close them. Two to four focused weeks on §11(a),
gated on one real end-to-end pilot campaign, separates this from a defensible launch.

*Generated as an independent pre-launch review; findings verified adversarially at HEAD
`1b48f01`. No business logic was changed on this branch by the audit itself.*

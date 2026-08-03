# Silk Market Intelligence — Consultancy-Grade Engineering Audit

> **Audited revision:** `main @ e3c19cb` (worktree checkout). **Method:** every claim cites `file:line`; every verifiable finding is **proven by execution** (real request/response, real timing, real browser) — the executed evidence is shown inline.
> **Remediation note:** the branch that carries this report (**PR #31**) already fixes the P0 security findings (C-1/M-1/M-2/L-1). Findings below describe **main before that merge**; each carries a remediation status.
> **Coverage:** all `silk_*.py`, `api.py`, `correlation.py`, `web/`, `tests/`, `docs/`. 108 tests on the branch (102 on main).

---

## 1 · Architecture

**Style.** Modular monolith → an implicit **layered pipeline** + a **multi-agent (Manager→Agents→Jury)** pattern + a **single canonical view-model**, all governed by one structurally-enforced invariant: *never fabricate data* (`silk_data_layer.py:58-66` `DataPoint`; failure path `:216-222`).

**Complete data flow.**
`api.analyze` (`api.py:267`) → `resolve()` HS6 (`silk_hs_resolver.py:95`, weak match→`None` `:120`) → `rank_markets()` scores ~38 markets on 4 weighted components (`silk_market_ranker.py:158`, weights `:56-61`) via `market_imports()` one-call size+rivals (`silk_data_layer_v2.py:27`) + World Bank income/pop → `ResearchManager.distribute()` runs 3 agents per top-3 market (`silk_agents.py:190-205`) → additive enrichment (`silk_engine.py:119-146`, `_enrich_*` `:218-370`) → `correlate()` **in-memory only** (`correlation.py:141`, purity note `:7-11`) → `synthesize()` deterministic jury + optional isolated Claude (`silk_synthesis.py:76-94`) → `build_view()` the ONE view-model (`silk_render.py:97-155`) → delivery (web / terminal / Word / brief / CSV / JSON). `POST /deepen` (`api.py:288`) is the same inside `silk_context.deepen_context()` — the only state a `PAID` agent may run (`silk_agents.py:74-82`).

**Strengths**
| # | Strength | Evidence |
|---|---|---|
| S1 | Invariant enforced structurally (missing≠0) | `silk_data_layer.py:137-151`; `silk_data_layer_v2.py:49`; `silk_trend.py:33-40` |
| S2 | One canonical view-model | `silk_render.py:97-155` |
| S3 | One verdict entry point (jury + isolated Claude) | `silk_synthesis.py:76-94` |
| S4 | Structural paid/free guard via contextvars | `silk_agents.py:69-92`; `silk_context.py:15-34` |
| S5 | Prompt-injection isolation, sanitizes its own delimiters | `silk_ai_judge.py:39-47` |
| S6 | Correlation engine pure (AST-tested) | `correlation.py:7-11` |
| S7 | Efficiency: one Comtrade call yields size+rivals | `silk_data_layer_v2.py:27-69` |

**Weaknesses**
| # | Weakness | Evidence |
|---|---|---|
| W1 | Sequential blocking I/O (latency ceiling) | `silk_market_ranker.py:171-194` — measured §4 |
| W2 | Untyped dicts mutated across stages | `silk_engine.py:150-169` |
| W3 | Procedural core: 20+ params / 14 `with_*` flags | `silk_engine.py:27-39` |
| W4 | No ports/repository abstraction (agents import data layer directly) | `silk_agents.py:14-22` |
| W5 | Import-time config capture (env changes post-import ignored) | `silk_data_layer.py:50` |

---

## 2 · Security (severity · exploitation · fix)

### 🔴 CRITICAL — C-1 · Unauthenticated, enumerable read of persisted product economics
**Location:** `api.py:398-410` (`/analyses`, `/analyses/{id}`), `:412-422` (`/brief`), `:424-446` (`/report.docx`) — none call `_require_key`. Persisted blob carries the cost card (`correlation.py:250-253` → `silk_storage.py:76-96`); IDs are `AUTOINCREMENT` (`silk_storage.py:49`).
**Exploitation (executed on main, `SILK_API_KEY` SET):**
```
GET /analyses/1   (no key) -> HTTP 200
  leaked product   : تمور فاخر
  leaked cost card : {'cost_per_unit': 12.5, 'shipping_per_unit': 2.0, 'tier': 'premium'}
GET /analyses     (no key) -> HTTP 200   (list of everyone's analyses)
GET /analyses/1/brief (no key) -> HTTP 200
```
Auth is configured yet the read routes ignore it → any anonymous client enumerates every client's cost basis.
**Fix (landed in this PR):** `_require_key(request)` on all four read routes; `hmac.compare_digest`. Re-proven: no key → **401**, correct key → **200**, wrong key → **401**.

### 🟠 MEDIUM — M-1 · No rate limiting
**Location:** entire `api.py` (documented absent at `docs/AUDIT_STATUS.md:319`).
**Exploitation (executed):** `30× GET /analyses → statuses = {200}` (no throttle). Each `/analyze` fans out ~150 upstream calls (§4), so a handful of req/s drains UN Comtrade / World Bank quota and the container.
**Fix (landed):** in-memory fixed-window limiter per key/IP; `SILK_RATE_LIMIT`/`_WINDOW`. Proven: 5× over limit 3 → `[200,200,200,429,429]`.

### 🟠 MEDIUM — M-2 · Paid cap fails **open** on DB error
**Location (main):** `silk_usage.py` `try_reserve_paid_calls` except-branch returns `True`.
**Exploitation (executed):** corrupt `usage.db` → `try_reserve_paid_calls(1) → True` → paid credit uncapped whenever the counter is unwritable.
**Fix (landed):** fail **closed** (`return False`); the free path never touches it. Proven: corrupt db → `False`, `/deepen{with_volza}` → **429**.

### 🟡 LOW
- **L-1 · timing-unsafe key compare** — `api.py:239` (`!=`). *Fixed in PR (compare_digest).*
- **L-2 · no security headers** on the `/`-mounted static UI — no CSP/X-Content-Type-Options/Referrer-Policy. *RESOLVED (Wave 8): a security-headers middleware now sets CSP + `nosniff` + `Referrer-Policy` on every response (`api.py`).*
- **L-3 · third-party font CDN** (`web/index.html:9`, `fonts.googleapis.com`) — supply-chain + breaks under strict CSP/offline. *Open.* Fix: self-host IBM Plex.
- **M-3 (owner-deferred)** — settings UI stores provider keys in `localStorage` the client never sends (`web/index.html` settings). Reconsider only if multi-user.

**Proposed fix (C-1/L-1), directly applicable:**
```python
# api.py
import hmac
def _require_key(request: Request) -> None:
    expected = _api_key_expected()
    if expected and not hmac.compare_digest(request.headers.get("x-api-key", ""), expected):
        raise HTTPException(401, "missing or invalid API key")

@app.get("/analyses/{analysis_id}")
def analysis(analysis_id: int, request: Request):
    _require_key(request); _rate_limit(request)
    ...
```

---

## 3 · Code Quality (issue · principle · location)

| # | Issue | Principle | file:line |
|---|---|---|---|
| Q1 | Flat 30+ module namespace, no package | Clean Architecture | repo root |
| Q2 | `analyze()` 20+ params / 14 `with_*` flags | SOLID SRP+OCP; Clean Code (long param list) | `silk_engine.py:27-39` |
| Q3 | Near-duplicate enrichment wrappers | DRY | `silk_engine.py:218-370` |
| Q4 | **Income fetched twice per market** (proven in §4 logs) | DRY / perf | `silk_market_ranker.py:179` vs `:184` |
| Q5 | Cross-module import of underscore-private symbols | Encapsulation / Clean Arch | `silk_synthesis.py:24` |
| Q6 | Untyped dicts as entities, mutated in place | DDD / immutability | `silk_engine.py:150-169` |
| Q7 | Import-time side effects (`_load_dotenv`, key capture, module `app`) | 12-Factor / testability | `silk_data_layer.py:34,50`; `api.py:449` |
| Q8 | ~40 broad `except Exception` (deliberate, masks bugs) | Error handling | pervasive |
| Q9 | Config reads scattered, no `Settings` | 12-Factor | `api.py`, `silk_data_layer.py`, `silk_storage.py`, `silk_usage.py`, `silk_ai_judge.py` |
| Q10 | 700-line single-file UI (self-contained by house rule) | Separation of concerns | `web/index.html` |
| Q11 | No linter / type-checker / coverage gate | Tooling | CLAUDE.md |

---

## 4 · Performance (ranked by impact, real measurements)

**Measurement harness:** each `requests.get` stubbed at a fixed **15 ms** RTT and counted; `rank_markets("080410", COUNTRIES, 2023)` run over the full market set.

| Rank | Bottleneck | Measured | Location | Fix |
|---|---|---|---|---|
| **P1** | Sequential blocking fan-out | **152 HTTP calls, 4.0/market, 2.35 s @15 ms → 22.8 s projected @150 ms RTT; 16-way pool ≈ 1.4 s (~16×)** | `silk_market_ranker.py:171-194` | `ThreadPoolExecutor` + shared `requests.Session` (house rule: requests, not httpx) |
| **P2** | No connection pooling (new TLS/call) | subset of the 152 | `silk_data_layer.py:182,206`; `silk_cache.py:51` | one `requests.Session(keep-alive)` |
| **P3** | **Redundant income fetch** — logs show `PP.CD, CD` **twice** per market | ~38 extra WB calls/run | `silk_market_ranker.py:179` & `:184` | reuse the one `DataPoint` |
| **P4** | Fixed 38-market universe every call | 38× base cost | `silk_market_ranker.py:26-53` | configurable/paged; region/sector prefilter |

**Memory/scalability:** bounded (modest dicts, no accumulation); SQLite adequate (owner-decided). Ceiling is I/O latency — replicas don't help until P1 concurrency + rate limiting (M-1) land.

---

## 5 · UI/UX (usability · a11y · responsiveness — real browser)

Tested in headless Chromium against the served app (intercepted `/analyze` to populate the table).

| # | Finding | Severity | Evidence (executed) | Location / fix |
|---|---|---|---|---|
| U1 | **Ranked-market rows not keyboard-operable** | a11y High | `rows with tabindex: 0`, `role: 0`, `a <tr> can take focus? False` | `web/index.html` table rows are `<tr onclick>` → add `role="button"`+`tabindex="0"`+Enter/Space |
| U2 | **Horizontal overflow at every width** | responsive Medium | `overflow px = {375: 525, 768: 140, 1280: 219}` | grid/flex children default `min-width:auto`; add `min-width:0` to `.body-grid > *` / `.card` so the wide table can shrink |
| U3 | Gauge `aria-label` is just the bare number | a11y Low | `gauge aria-label: '0.71'` | make it descriptive ("decision confidence 0.71") |
| U4 | Slow `/analyze` shows only a skeleton (P1) | usability | (see §4) | progressive render + cancel |
| — | No JS/page errors; language + theme toggles work | ✅ | `PAGE ERRORS: none` | — |

**Strengths (verified):** decision-first hierarchy + confidence gauge; truthful pipeline + completeness meter; provenance under every number; gaps as "not observed"; live AR⇄EN RTL/LTR via CSS logical properties; light/dark; 16px base high contrast; `:focus-visible`; `prefers-reduced-motion`.

---

## 6 · Spec Compliance (V3 documented features vs current main)

**Governance fact:** the repo contains **no "V3 plan" document** — stated verbatim at `docs/AUDIT_STATUS.md:407-410` ("لا توجد وثيقة «خطة V3» داخل المستودع — غير موجود، بحث شامل"). The roadmap is `docs/EXECUTION_PLAN.md` (waves 0–5). Comparison below is VISION/plan intent vs `main`.

| Documented feature | In main? | Classification |
|---|---|---|
| Auth on API (`/analyze`, `/deepen`) | ✅ present (`api.py:236-242,271,296`) | Implemented (Wave 0) |
| **Auth on read endpoints** | ❌ (C-1) | **Silently absent — no decision** *(fixed in PR #31)* |
| Cost cap (paid daily) | ✅ present (`silk_usage.py`, `api.py:244-265`) | Implemented (Wave 0) |
| **Rate limiting** | ❌ (`AUDIT_STATUS.md:319`) | **Silently absent — never scoped in any wave** *(added in PR #31)* |
| **Background job queue (RQ/worker/redis)** | ❌ — **zero** occurrences in code/docs/git history | **Silently absent — never planned or present** |
| Prompt-injection isolation | ✅ (`silk_ai_judge.py:39-47`) | Implemented (Wave 0) |
| Correlation engine + product card | ✅ (`correlation.py`, `api.py:130-137`) | Implemented (Wave 4) |
| Two-stage synthesis / single verdict | ✅ (`silk_synthesis.py`) | Implemented (Wave 4) |
| Unified view template | ✅ (`silk_render.py:97`) | Implemented (Wave 4) |
| Four deliverables (dashboard, Word, brief, samples) | ✅ (`web/`, `silk_reports.py`, `samples/`) | Implemented (Wave 1/5) |
| **21-agent target** | ❌ (11 present) | **Dropped by documented decision** (`EXECUTION_PLAN.md:66-75,109`) |
| 6 non-core agents (cultural/exhibitions/religion/currency/ecommerce/factories) | ❌ | **Dropped by documented decision** (`EXECUTION_PLAN.md:75,109`) |
| Postgres migration | ❌ (SQLite) | **Dropped by documented decision** (`EXECUTION_PLAN.md:105-108`) |
| Trade-finance layer (§12.7) | ❌ | **Dropped by documented decision** (`EXECUTION_PLAN.md:113-114`) |
| Security headers (CSP) | ❌ | **Silently absent — no decision** (L-2) |

**Verdict:** no feature was "completed then lost." Gaps are either (a) **owner-deferred by documented decision** (agents, Postgres, trade finance) or (b) **never-scoped gaps** (read-auth, rate limiting, RQ queues, security headers) — of which read-auth + rate limiting are remediated by PR #31.

---

## Checked & Clean (verified sound — coverage, not just findings)

| Area | Verified | Evidence (executed / cited) |
|---|---|---|
| **SQL injection** | Clean — parameterized | payload `'; DROP TABLE analyses;--` stored verbatim, table intact, 1 row; `silk_storage.py:78-94` all `?` params |
| **CORS** | Clean — same-origin default | `GET /health` w/ `Origin: evil` → **no** `Access-Control-Allow-Origin` header; `api.py:125-128` (middleware only if `CORS_ORIGINS` set) |
| **API-key leakage** | Clean | `/sources` body does **not** contain the raw `GOOGLE_MAPS_API_KEY` value (only `key_present` bool); `api.py:362-366` |
| **Missing-not-zero invariant** | Clean | offline `TradeFlowAgent` → `failed=True, value=None` (not 0); `silk_agents.py:117-134` |
| **Prompt-injection isolation** | Clean | delimiters sanitized from content; `silk_ai_judge.py:39-47` + test `test_wave0_security.py:147` |
| **Dangerous sinks** | Clean | repo-wide sweep: no `eval/exec/os.system/subprocess/pickle/yaml.load/shell=True/verify=False` |
| **Paid/free structural guard** | Clean | `PAID` agent outside deepen → skipped, no call; `silk_agents.py:74-82` |

---

## 7 · Recommendations (P0–P3, applicable code)

**P0 — Security (LANDED in PR #31):** C-1 read-auth, M-1 rate limit, M-2 fail-closed, L-1 constant-time. **Ops action:** set `SILK_API_KEY` in Railway Variables — `.env.example:17` ships blank and `railway.json` doesn't set it, so without it the guard is a dev-mode no-op (`docs/DEPLOY_RAILWAY.md:40`).

**P1 — Concurrency (LANDED, Wave 8):** `rank_markets` now fans the ~38 markets out over `ThreadPoolExecutor(max_workers=16)` with a pooled keep-alive `requests.Session`, and the duplicate income fetch (Q4) is removed. **Measured before/after** (same §4 harness): **228→152 HTTP calls** and **3.51s→0.19s @15ms** (~18.5×). Example below.
```python
# silk_market_ranker.py — fan out the 38 markets; keep sync path for hermetic tests
from concurrent.futures import ThreadPoolExecutor
_SESSION = requests.Session()                     # P2: pooled keep-alive
def rank_markets(hs_code, countries=None, year=2022, max_workers=16):
    countries = countries or COUNTRIES
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        rows = list(ex.map(lambda c: _gather_row(hs_code, c, year), countries))
    ...   # 22.8s → ~1.4s at 150ms RTT (measured §4)
```
Plus dedupe the double income fetch (`silk_market_ranker.py:179`/`:184`).

**P2 — Architecture/quality:** `silk/` package (domain/application/adapters/interface) with re-export shims; enrichment registry (OCP); frozen `DataPoint` + typed `Market`/`ScoredMarket`; single `Settings`; add `ruff`+`mypy`+coverage gate.

**P3 — UI/UX:**
```html
<!-- web/index.html — keyboard-operable rows (U1) + kill overflow (U2) -->
<tr role="button" tabindex="0" data-id="..."></tr>
<style>.body-grid > *{min-width:0}  /* let the wide table shrink instead of overflowing */</style>
```
Plus self-host fonts (L-3), progressive render + cancel (U4), descriptive gauge label (U3).

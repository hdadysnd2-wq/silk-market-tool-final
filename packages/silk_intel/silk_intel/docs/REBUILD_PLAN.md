# Silk Market Intelligence — Rebuild Plan (Phase 2)

> **الخلاصة:** لا نهدم — نبني فوق الأصول القوية المُثبَتة (مبدأ لا-اختلاق البنيوي، نموذج العرض الموحّد، حواجز المدفوع/المجاني، الواجهة ثنائية اللغة) ونعيد كتابة أربع طبقات ناقصة: **مخزن حقائق حقيقي + خطّ بيانات مُجدوَل**، **محرّك قرار موزون (30/25/20/25) بفئة Conditional-Go**, **قالب تقرير احترافي كامل**، و**مستخدمون/أدوار + شاشات المنتج**. تنفيذ على فرع `rebuild` بمعالم صغيرة قابلة للاختبار.

**Guiding constraint (non-negotiable):** the founding no-fabrication principle survives every change. TAM/SAM/SOM and any modeled figure is presented as a **disclosed-assumption model** (formula + inputs + provenance shown), never as an observed fact.

---

## 1. Target architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  UI (web/) — design-system components, 8 screens, AR/EN RTL/LTR    │
├─────────────────────────────────────────────────────────────────────┤
│  API v1 (FastAPI) — auth/roles · error envelope · pagination        │
├──────────────┬───────────────────────────┬──────────────────────────┤
│ DECISION     │ REPORT GENERATION          │ PROCESSING & ANALYSIS    │
│ engine/      │ reports/ (docx·md·pdf)     │ engine, ranker, agents,  │
│ weighted     │ from view model only       │ correlation, synthesis   │
│ rubric       │                            │ (existing, refactored)   │
├──────────────┴───────────────────────────┴──────────────────────────┤
│  STORAGE — one SQLite (Postgres-ready): facts + analyses + users    │
├─────────────────────────────────────────────────────────────────────┤
│  DATA COLLECTION — budgeted collectors · per-source TTL cache ·     │
│  seed snapshots · scheduled refresh (worker) · provenance DataPoint │
└─────────────────────────────────────────────────────────────────────┘
```

Module layout evolves from flat root to packages **gradually** (each move covered by tests): `silk/data/` (layer+cache+collectors+seeds), `silk/agents/`, `silk/analysis/` (engine, ranker, correlation, synthesis), `silk/decision/`, `silk/reports/`, `silk/api/`, `web/`. Root shims re-export during transition so nothing breaks mid-milestone.

---

## 2. Keep / rewrite / delete

| Decision | Item | Justification |
|---|---|---|
| **KEEP as-is** | `DataPoint` provenance contract; `BaseAgent` structural guard; deepen contextvar; `silk_usage` atomic fail-closed cap; prompt-injection quarantine; HS resolver + CSVs; `correlation.py`; hermetic-test culture | Proven, tested, the platform's soul |
| **KEEP & extend** | `silk_render.build_view` (add decision/report fields); `silk_market_ranker` (becomes the *market-attractiveness pillar* input); SPA design language (Carbon×Redwood tokens); Dockerfile/Railway/healthcheck | Strong foundations, wrong scope only |
| **REWRITE** | Storage → real fact schema (§3); cache → per-source TTL policy + eviction; reports → full professional template (§7); verdict → weighted decision engine (§8); api → v1 + envelope + pagination + roles (§5–6); frontend → modular components + new screens (§9); Comtrade fetching → budgeted queue w/ backoff (§4) | The four target gaps |
| **PORT from session branch** | World Bank seed snapshot + loader (offline real fallback); `SILK_AI_TOKEN_CAP` pre-flight Claude cost cap + visible cap-cut markers; Sonnet-default model | Already built & proven in PR #11; cherry-pick, not blind-merge |
| **DELETE** | `data/cache/analysis:*.json` (dead artifacts — **after your confirmation**, per constraint); `ai_report` parallel Claude path (fold into synthesis stage-2); `format_result` shim; duplicate `DataPoint` def in hs_resolver | Dead/duplicated |
| **DEMOTE** | `app.py` Streamlit → `tools/dev_console.py` (or delete if you prefer) | Debug tool, not product |

---

## 3. Database design (one DB; SQLite default, `DATABASE_URL` → Postgres-ready via thin adapter)

```sql
-- Users & access
users(id PK, email UNIQUE, name, role CHECK(role IN('admin','analyst','viewer')),
      pw_hash NULL, created_at, active)
sessions(id PK, user_id FK, token_hash UNIQUE, created_at, expires_at)
api_keys(id PK, user_id FK, key_hash UNIQUE, label, created_at, revoked_at NULL)

-- Reference
markets(iso3 PK, m49, name_ar, name_en, region, gcc BOOL, eu BOOL)
hs_codes(hs6 PK, name_ar, name_en, keywords)          -- from existing CSV

-- FACT STORE (the new core — queryable, provenance-preserving)
indicators(id PK, iso3 FK, indicator, year, value REAL NULL, source,
           confidence, note, retrieved_at,
           UNIQUE(iso3, indicator, year, source))      -- WB pop/GDP/PPP, WITS tariff…
trade_flows(id PK, hs6, reporter_iso3, partner_iso3, year,
            flow CHECK(flow IN('M','X')), value_usd NULL, qty_kg NULL,
            source, retrieved_at,
            UNIQUE(hs6, reporter_iso3, partner_iso3, year, flow))
collection_runs(id PK, source, started_at, finished_at, requested, fetched,
                failed, budget_left, note)             -- pipeline audit trail

-- Analyses & outputs
analyses(id PK, user_id FK NULL, product, hs6, year_from, year_to,
         status, created_at, result_json)              -- full blob stays for fidelity
analysis_markets(id PK, analysis_id FK, iso3, rank, total_score, confidence,
                 comp_market_size, comp_demand, comp_saudi, comp_competition)
decisions(id PK, analysis_id FK, iso3, verdict CHECK(verdict IN('GO','CONDITIONAL-GO','NO-GO')),
          score, confidence, pillar_market REAL NULL, pillar_competition REAL NULL,
          pillar_regulatory REAL NULL, pillar_profit REAL NULL,
          conditions_json, risks_json, first_steps_json, created_at)
reports(id PK, analysis_id FK, kind CHECK(kind IN('full','brief')),
        format CHECK(format IN('docx','md','pdf')), path, created_at)
outcomes(analysis_id FK PK, outcome, note, recorded_by FK users, recorded_at)
```

Migrations: sequential `migrations/00N_*.sql` + tiny runner (stdlib); every milestone that touches schema ships one. Existing `silk.db` analyses imported by a one-off script (kept, per "never delete data" constraint).

---

## 4. Data pipeline

**Collectors (new `silk/data/collectors/`)** — one per source, all writing to the fact store with provenance:
- **Comtrade collector (budgeted):** priority queue (requested markets first, then staleness); daily budget ledger (default 450 with key, persisted in `collection_runs`); token-bucket pacing + exponential backoff + `Retry-After` respect; keyless mode = max 4 serial requests/run + clear "limited preview" banner. Closed trade years cached **30 days**; current year 24 h.
- **World Bank collector:** bulk per-indicator fetch (all countries in one call — WB supports `country=all`), refresh **7 days**; falls back to the **bundled real seed snapshot** (ported) so demographics/income are never empty offline.
- **WITS tariffs:** refresh 30 days; per-pair on demand + cache.
- **Serper/Maps/paid:** stay request-time (fresh by nature) but gain response caching (Serper 3 days) and the existing paid cap.

**Refresh strategy:** a `worker` process (same image, `python -m silk.data.refresh`) run by Railway cron/scheduled job: tops up stale facts within budget, records a `collection_runs` row. `analyze()` reads facts from the store first; live-fetches only misses (and enqueues them for the collector).

**Cost/rate-limit handling:** per-source budget table; `/v1/admin/usage` exposes spend; paid layers keep the atomic daily cap; Claude keeps the ported pre-flight token cap with visible cap-cut markers.

**Staleness-aware confidence:** effective_confidence = source_prior × age_decay(retrieved_at, half-life per source). Shown in provenance lines.

---

## 4b. Multi-agent research architecture — وكلاء البحث المتخصصون

The existing `ResearchManager` + `BaseAgent` evolve into a schema-validated **Orchestrator + five specialized research agents**. This layer sits between the data pipeline (§4) and the decision engine (§8): collectors fill the fact store → agents read facts (+ targeted live calls within budget) → orchestrator validates & aggregates → decision engine consumes pillar inputs → report consumes section outputs.

### The five research agents

| Agent | Scope | Data sources | Feeds |
|---|---|---|---|
| **1. Market Size Agent** | TAM/SAM/SOM for HS6×market: TAM = observed total imports; SAM = TAM × disclosed segment filters (product-card tier); SOM = capacity/price-position scenario. Growth: YoY, CAGR, seasonality | `trade_flows` (Comtrade, free-keyed), Trends (optional), product card | Pillar: market attractiveness · Report §2–3 |
| **2. Competitor Agent** | Exporters to target market with shares + HHI; named-company candidates; positioning (price tier vs. yours via correlation) | `trade_flows` partners (Comtrade), Serper candidates (0.4-conf, flagged unverified), Volza/Explee (paid, deepen-only), correlation threads | Pillar: competition intensity · Report §4 |
| **3. Regulatory Agent** | Customs procedure, applied tariff, standards/certifications (halal, labeling, animal-origin chain), trade agreements (GCC/GAFTA/EU flags) | WITS (free), `requirements_l1.csv` + live verify (Serper), `markets` reference (agreement flags), `indicators` | Pillar: regulatory fit · Report §6 |
| **4. Pricing Agent** | Target-market retail prices, price trend, your position percentile, margin-at-match, landed-cost line | Web price signals (Serper, free), SerpApi structured listings (paid, deepen-only), correlation feasibility thread, tariff (landed cost) | Pillar: profitability margin · Report §7 |
| **5. Risk Agent** *(new)* | Political stability, currency risk, logistics risk, supplier-concentration & data-coverage risk | **All free via existing WB collector:** WGI (`PV.EST`, `RQ.EST`), LPI (`LP.LPI.OVRL.XQ`), FX series (`PA.NUS.FCRF`) volatility + bundled peg reference; HHI from `trade_flows` | Risk register + critical-risk gate + confidence modifiers · Report §10 |

### Output schema (per agent, pydantic-validated)

```json
{
  "agent": "market_size", "hs6": "080410", "iso3": "ARE",
  "status": "complete | partial | failed",
  "findings": [{"metric": "tam_usd", "value": 270000000,
                "modeled": false, "formula": null,
                "sources": [{"source": "UN Comtrade", "retrieved_at": "…", "confidence": 0.9}],
                "note": "…"}],
  "gaps": ["som: no product_card capacity supplied"],
  "coverage": 0.75, "started_at": "…", "finished_at": "…"
}
```

Schema rules enforce the doctrine **per agent**: every finding requires a non-empty `sources[]`; `value=null` requires a `gaps[]` entry; any `modeled:true` figure requires `formula` + inputs. A finding violating the schema is **rejected at validation**, logged, and downgraded to a gap — it can never reach the fact store, the report, or the decision engine uncited.

### Orchestrator (`silk/analysis/orchestrator.py`)

Evolves `ResearchManager`; keeps `BaseAgent`'s structural guards (paid-outside-deepen impossible; silent failure impossible). Responsibilities:
1. **Parallel dispatch** — the five agents per target market via `ThreadPoolExecutor`, each with a timeout; shared read access to the fact store, live calls only through the budgeted collectors (§4).
2. **Schema validation** — each output validated against its pydantic schema; invalid → `status:"failed"` with reason.
3. **Aggregation** — validated findings upserted into `indicators`/`trade_flows`/analysis rows with provenance; section outputs attached to the analysis for `build_view`.
4. **Hand-off** — emits the pillar-input bundle consumed by the weighted decision engine (§8) and the section bundle consumed by the report (§7).

### Failure handling (non-blocking, honest)

If an agent fails or times out: its **report section renders as `⚠ ناقص — incomplete`** with the failure reason and what source/key would complete it; its **pillar is treated as missing** → §8's missing-pillar policy applies (weights renormalized, the gap becomes a Conditional-Go condition); overall **confidence is reduced** by the coverage formula (`confidence = Σ agent_coverage×weight / Σ weight`, staleness-decayed) — computed, printed with its basis. One failed agent **never blocks** the other four or the report; a `collection_runs`-style `agent_runs` row records every run for the admin screen.

### Milestone placement

| Component | Milestone |
|---|---|
| Risk-agent data substrate (WGI/LPI/FX indicators via WB collector + peg reference CSV) | **M2** (data pipeline) |
| Orchestrator + all five agents v1 + schemas + failure handling (Pricing v1 = free web signals; paid listings stay deepen-only) | **M3a** |
| Decision engine consuming the pillar bundle | **M3b** |
| Report sections wired to agent outputs (incl. `⚠ incomplete` rendering); Pricing deepen integration | **M4** |
| Agent-run visibility (admin screen: per-agent status/coverage/budget) | **M6** |

---

## 5. API specification (`/v1`, FastAPI)

Conventions: error envelope `{"error":{"code","message","details?"}}`; cursor pagination `?limit=&after=` (limit clamped ≤100); all bodies pydantic-validated; OpenAPI served at `/v1/docs`.

| Method & path | Role | Purpose |
|---|---|---|
| POST /v1/auth/login · POST /v1/auth/logout | public | session (email+password; magic-link optional later) |
| GET /v1/me | any | current user + role |
| GET /v1/markets · GET /v1/markets/{iso3} | viewer+ | reference + latest facts |
| GET /v1/products/resolve?q= | viewer+ | HS resolution |
| POST /v1/analyses | analyst+ | run analysis (free layers) |
| POST /v1/analyses/{id}/deepen | analyst+ | paid layers (cap-guarded) |
| GET /v1/analyses · /{id} | viewer+ | paginated history · full result+view |
| GET /v1/analyses/{id}/decision | viewer+ | decision object (verdict, pillars, risks, steps) |
| GET /v1/analyses/{id}/report?format=md\|docx\|pdf | viewer+ | generated report |
| PATCH /v1/analyses/{id}/outcome | analyst+ | **fixed: auth + rate-limit** |
| POST /v1/discover · POST /v1/trend | analyst+ | existing capabilities, versioned |
| GET /v1/sources | analyst+ | key_present now auth-gated |
| GET /v1/admin/users · POST/PATCH … | admin | user management |
| GET /v1/admin/usage · /v1/admin/collections | admin | budgets, collection runs |
| GET /health | public | unchanged |

Legacy unversioned routes stay as deprecated aliases for one milestone, then removed.

---

## 6. Authentication & user management

- `users` with roles **admin / analyst / viewer** (matrix above). First-run bootstrap: `ADMIN_EMAIL`+`ADMIN_PASSWORD` env creates the admin.
- Passwords: `pbkdf2_hmac` (stdlib, 600k iters) — no new dependency; magic-link (session-branch asset) optional later.
- Sessions: opaque token, **hash stored**, 30-day expiry, `Authorization: Bearer`. Constant-time compares everywhere.
- `SILK_API_KEY` retained as a machine/service key mapped to an `api_keys` row (analyst role) — backward compatible.
- Rate limiting: honor `X-Forwarded-For` (first hop) behind Railway; keep in-memory default, Redis optional via env.

---

## 7. Final report template (docx + Markdown; PDF from the same content)

Every number keeps its source line; every modeled figure shows formula + inputs; gaps stay declared. Sections:

1. **Executive summary** — verdict + confidence gauge, top-3 numbers, one-paragraph rationale.
2. **Market size — TAM/SAM/SOM** *(modeled, disclosed)*: TAM = market's total imports of HS6 (Comtrade, observed). SAM = TAM × addressable filters (segment/tier from product card; shown as assumption). SOM = scenario from capacity & price-position percentile (formula printed). Each labeled `مُقدَّر — نموذج بافتراضات معلنة`.
3. **Growth trends** — multi-year imports, YoY, CAGR, seasonality (Trends when available).
4. **Competitor analysis** — supplier-country shares (HHI), named-company profiles (candidates flagged unverified; Volza/Explee verified when deepened), price-point table.
5. **SWOT** — rule-derived from observed facts (e.g. S: existing Saudi share, price advantage; W: missing certifications; O: growth+low HHI; T: dominant supplier, tariff) — each cell cites the fact that produced it; empty cells declared.
6. **Regulatory environment** — requirements-agent checklist **wired into the docx** (entry + Saudi-exit, authority + source URL per item).
7. **Pricing analysis** — observed listings, your position percentile, margin-at-match from correlation, landed-cost line (tariff + shipping from product card).
8. **Customer segments** — income tier × consumption-culture signals; declared-gap when unobserved.
9. **Distribution channels** — channels-agent output + e-commerce landscape.
10. **Risks** — generated risk register (§8 outputs): concentration, tariff, volatility, regulatory unknowns, data-coverage — each with severity & evidence.
11. **Decision** — full §8 output: pillar breakdown bars, conditions (if conditional), first steps.
12. **Methodology & sources appendix** + limits + disclaimer (existing discipline).

---

## 8. Market-entry decision engine (`silk/decision/`)

**Score = 0.30·MarketAttractiveness + 0.25·(1 − CompetitionIntensity) + 0.20·RegulatoryFit + 0.25·ProfitabilityMargin** — each pillar ∈ [0,1], computed **exclusively from the validated agent bundle (§4b)**: Market Size Agent → attractiveness, Competitor Agent → intensity, Regulatory Agent → fit, Pricing Agent → profitability; the Risk Agent contributes the risk register, the critical-risk gate, and confidence modifiers. Pillar inputs:

| Pillar | Inputs (all provenance-tagged) |
|---|---|
| Market attractiveness (.30) | normalized import size, import CAGR, demand capacity (income), Saudi-share momentum |
| Competition intensity (.25) | HHI, top-supplier share, named-competitor density, price dispersion |
| Regulatory fit (.20) | requirements-checklist coverage (met/known/unknown), tariff level normalized, eligibility flags (halal/animal-origin chain) |
| Profitability margin (.25) | margin at price-match percentile (needs product_card + observed prices); landed-cost vs. market median |

### 8a. Weight justification & the alternative (owner decision required before M3b)

> **قرار البوابة GATE 3 (2026-07-06):** اعتمد المالك التوصية — **الخيار A هو المعتمد**
> (تابع التنفيذ بعد عرض الخيارين والتوصية). كلا المجموعين يُحسبان ويظهران في كل
> قرار (`scores_by_option`)، و`SILK_DECISION_WEIGHTS=B` يبدّل المعتمد دون كود.
> القرار قابل للمراجعة بعد الاختبار الرجعي الحي على النشر
> (`tools/refresh.py` ثم `tools/backtest.py`).

**Option A — approved baseline 30/25/20/25:** mirrors standard market-entry frameworks: demand-side pull (attractiveness + profitability = 55%) leads, rivalry (25%) second, regulation (20%) third — because regulation in this engine is **not only a weight, it is also a hard gate**: critical ineligibility (e.g. animal-origin chain ineligible, embargo) forces NO-GO regardless of score, and unmet checklist items become CONDITIONAL-GO conditions. The gate carries the compliance risk, so the scalar weight can stay moderate without underweighting compliance. Best when the goal is **opportunity scanning**: find the biggest winnable markets.

**Option B — regulatory-heavy 25/20/30/25** (market 25 / competition 20 / **regulatory 30** / profitability 25): for Saudi food/agri exports (dates, honey, …) the most common *practical* failure point is certification/halal/labeling/import procedure, not demand. Raising regulatory to the top weight systematically favors markets with trade agreements (GCC/GAFTA zero-tariff, known chains) and makes the score itself — not just the conditions list — sensitive to compliance readiness. Trade-off: mid-size easy-regulation markets can outrank larger, tougher ones — a **conservative, execution-first** ranking.

**Guidance:** SME users new to exporting (execution risk dominates) → B. Portfolio/strategic scanning (size of prize dominates) → A. Both keep the critical-regulatory gate and identical pillar definitions; weights live in one config constant. **M3b will ship a sensitivity test running both weight sets on the golden cases and reporting any verdict flips**, so the choice is evidence-backed at go-live.

**Missing-pillar policy (no fabrication):** absent pillar ⇒ weights renormalized over present pillars **and** confidence capped; the missing pillar is emitted as a *condition*. **Confidence** = data-coverage × mean effective source confidence (staleness-decayed) — a principled aggregate, printed with its formula.

**Verdict mapping:**
- `GO` — score ≥ 0.65 **and** confidence ≥ 0.60 and no critical risk flag
- `CONDITIONAL-GO` — score ≥ 0.45, or score ≥ 0.65 with confidence < 0.60 → conditions = the weak/missing pillars & unmet checklist items
- `NO-GO` — score < 0.45, or critical regulatory ineligibility

**Outputs:** verdict, total score, per-pillar breakdown (for the UI visual), confidence + basis, key risks (top-N from the risk rules), recommended first steps (rule playbook keyed on verdict + weakest pillar), conditions. The existing jury remains as a **data-sufficiency gate** in front of the engine (insufficient data ⇒ engine abstains honestly). Claude stage-2 becomes *narrative explanation* of the computed decision — never the decision itself.

---

## 9. UI/UX design specification

**Design system (formalize the existing Carbon×Redwood into `web/tokens.css` + `web/components/`):**
- Palette: primary `#0F62FE`, accent `#C74634`, semantic (success/warn/danger), full light+dark token pairs (existing), neutrals scale.
- Type: IBM Plex Sans / Plex Sans Arabic / Plex Mono; scale 12/14/16/20/24/32; numerals always LTR.
- Spacing 4-px scale; radii 8/12; tokenized shadows & easing (existing).
- Components: buttons, inputs/selects, cards, tables (sortable, overflow-safe), tabs, badges, gauge, score-bars, pillar-breakdown chart, toasts, skeletons, modals, empty/error blocks — each with RTL mirror + dark variant.
- **Charts:** vendored **uPlot** (~45 KB, self-hosted — CSP-friendly, no CDN): market-size bars, multi-year trend lines, supplier-share donut, pillar radar/stacked-bar. Hand-rolled sparklines retained in tables.

**Bilingual:** existing i18n dictionary pattern extended; `dir` switching + CSS logical properties (already correct); all new screens ship AR+EN from day one.

**Screens (each with loading/empty/error states):**
1. **Login** — email/password, error states, AR/EN toggle.
2. **Dashboard** — KPI tiles (analyses run, GO rate, coverage, budget), recent analyses, market-map/chart.
3. **Market search & selection** — product typeahead → HS confirm → year range + product card → run.
4. **Analysis progress** — the existing agent-pipeline strip, live.
5. **Report viewer** — sectioned report with export buttons (PDF/MD/docx).
6. **Decision screen** — verdict hero + **pillar breakdown visual** + conditions + risks + first steps.
7. **History** — paginated, filterable, outcome recording.
8. **Admin/settings** — users & roles, **server-side key status (read-only truth — fixes the misleading keys panel)**, budgets/usage, caps.

**Responsive:** existing breakpoint approach; tables → cards on mobile; 6-tab detail becomes accordion under 640 px. **Accessibility:** keep focus-visible/aria/keyboard patterns; contrast-check tokens.

---

## 10. Non-functional requirements

- **Performance:** warm-cache analysis P50 < 10 s / P95 < 30 s; fact-store repeat < 1.5 s; report render < 3 s; UI TTI < 2 s on 3G-fast.
- **Logging:** stdlib `logging` + JSON formatter, request-ID middleware, per-request access log (path, status, ms, user).
- **Error tracking:** optional Sentry via `SENTRY_DSN` (no-op unset).
- **Backups:** nightly `sqlite3 .backup` to `/data/backups/` (7-day rotation) via the worker; documented restore.
- **Testing bar:** every milestone = tests first; suite stays hermetic; add frontend smoke via Playwright (chromium already available in CI image) for the 8 screens.

## 11. Deployment plan

- **Dockerfile** (extend existing): non-root user, `PYTHONUNBUFFERED`, healthcheck.
- **docker-compose.yml**: `app` + `worker` (refresh/backups) sharing a volume; optional `postgres` profile.
- **.env.example**: regenerated — all vars grouped (auth, sources, budgets, caps, ops) bilingual comments.
- **CI:** pytest + ruff + pip-audit on every push; pinned `requirements.txt` (`==`) + `constraints.txt`; Railway deploy gated on CI checks; Playwright smoke on PRs.

---

## 12. Milestones (small, testable, priority order)

| # | Milestone | Contents | Exit criteria |
|---|---|---|---|
| **M0** | Hotfixes | PATCH outcome auth+rate-limit; clamp /index limit; gate /sources key flags; pin deps; conftest.py shared `_block_network` | suite green + new regression tests |
| **M1** | Storage & schema | migrations runner; §3 schema; import legacy silk.db; storage adapter (SQLite/Postgres) | CRUD tests; legacy import verified |
| **M2** | Data pipeline | fact-store reads in ranker/agents; Comtrade budgeted collector + backoff; WB bulk (**+ WGI/LPI/FX for Risk Agent**) + seed port; per-source TTL cache; worker refresh + collection_runs | keyless=honest-limited, keyed=38/38 in test-double; budget ledger tests |
| **M3a** | Research agents & orchestrator (§4b) | five agents v1 + output schemas + parallel orchestrator + validation + non-blocking failure handling + agent_runs | per-agent schema tests; one-agent-down → 4 sections + reduced confidence |
| **M3b** | Decision engine | pillars **from the agent bundle**, scoring, verdict mapping, conditions/risks/first-steps, confidence; jury as sufficiency gate | golden-case tests incl. missing-pillar & Conditional-Go |
| **M4** | Reports | full template §7 (docx+md), SWOT/regulatory/channels wiring, TAM-SAM-SOM disclosed models; realistic committed sample | structure tests; sample renders non-empty |
| **M5** | API v1 | versioning, envelope, pagination, auth/roles endpoints, admin routes; legacy aliases | endpoint tests incl. role matrix |
| **M6** | UI system + screens | tokens/components; login, dashboard, search-flow, decision, report viewer, history, admin | Playwright smoke per screen, AR+EN |
| **M7** | PDF + polish | PDF export (docx→pdf where LibreOffice; else print-CSS md→pdf), decision visuals, onboarding first-run | export tests; visual review checkpoint **(screenshots to you)** |
| **M8** | Ops hardening | JSON logs+request IDs, Sentry hook, backups, CSP nonce, docker-compose, CI gates | ops checklist green |
| **M9** | Finalization | full regression, dead-code sweep, README, CLAUDE.md, docs/HANDOVER.md | all tests green; docs complete |

Rollout: each milestone = PR into `rebuild`; `rebuild` → `main` only at your sign-off checkpoints (after M4, M7, M9). Operational prerequisite in parallel: set **`COMTRADE_API_KEY`** (free) on Railway.

---

**⏸ STOPPED — awaiting your approval** (per the phase gate). Approve as-is, or mark changes to any section, and Phase 3 (M0) starts on branch `rebuild`.

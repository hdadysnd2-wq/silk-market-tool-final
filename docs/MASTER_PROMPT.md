# Master Prompt — Merge Silk-market-intelligence + silk-market-tool- into One Product

> This is the governing specification for the monorepo merge. Architecture
> decisions here are **final** — implement them, don't re-litigate. Phase 0 is
> recorded in `architecture.md` and `PROVENANCE.md`.

## Mission

A single product with this end-to-end pipeline:

**Factory uploads a product image → system proposes an HS Code (human must
confirm) → system scans ALL world markets and funnels down to the top 5 best-fit
export countries → for each of the 5 countries, lists competing products with
observed prices → produces verified potential-buyer email lists per country →
drafts a personalized outreach email per buyer in the buyer's language → sends
ONLY after explicit human approval, via cold-email infrastructure, with
tracking.**

## Source repositories

- **Repo A — the BRAIN (intelligence engine):** `hdadysnd2-wq/Silk-market-intelligence` (`main`).
  Multi-agent Python market-intelligence engine. `DataPoint` provenance model
  ("never fabricate data"), `silk_hs_resolver` + `silk_hs_confirm`,
  `silk_market_ranker`, `correlation.py`, `silk_discovery.py`, unified
  `silk_render.build_view` → Word report + one-page brief, production-grade
  `silk_data_layer` (pooling, throttling, backoff+jitter, circuit breaker, disk
  cache with per-source TTL, mirror fallback), FastAPI `api.py`, SQLite storage,
  usage caps, prompt-injection isolation, cost ceilings, `contextvars`-based
  `/deepen` guard.
- **Repo B — the BODY (product shell + campaign machinery + UI):**
  `hdadysnd2-wq/silk-market-tool-` (`claude/saudi-export-intelligence-mvp-9bpu73`).
  FastAPI + Celery + SQLAlchemy + Alembic + Postgres/pgvector + Redis; Next.js
  App Router + TypeScript + Tailwind + next-intl (Arabic RTL-first). Provider
  abstraction returning `ProviderRecord[T]` with deterministic mocks for every
  provider (runs locally with ZERO API keys). 3-layer human send-approval
  (API → worker `SELECT … FOR UPDATE` → DB `CHECK`), cross-tenant suppression
  list, append-only audit log (DB trigger), per-factory OAuth sending with
  Fernet-encrypted tokens, warm-up logic. Terraform skeleton for `me-south-1`.

## Final architecture decisions (locked)

1. One monorepo. **Modular monolith** on Repo B's skeleton. No microservices.
2. Repo A's engine becomes internal package `packages/silk_intel`, consumed by
   Celery workers via direct Python imports.
3. Storage unified on **PostgreSQL** (+ Redis). Repo A's SQLite + disk cache
   replaced behind a thin adapter on the `silk_storage` interface. This
   deliberately supersedes the standalone-engine decisions in
   `EXECUTION_PLAN.md` (#1 "SQLite stays", #5 "no Redis/RQ queues"), which
   govern the engine as a standalone tool — not the merged product
   (owner-confirmed 2026-08-03).
4. `DataPoint` / `ProviderRecord` merge into ONE contract
   (`{value, source, provider, confidence, fetched_at, data_year, note}`). Every
   number carries this envelope. On failure: `value=None, confidence=0.0` + note.
5. External tools (final verdicts):
   - `comtradeapicall` → **HYBRID**: offline ETL (`etl/`) bulk downloads only;
     **pandas allowed in `etl/` only**. Live Comtrade keeps Repo A's
     `silk_data_layer`.
   - **Meilisearch → DEFERRED.** HS stays difflib + human confirm; app search
     uses Postgres FTS/`pg_trgm`.
   - **warmbly → REJECTED.** Sending = Smartlead/Instantly + per-factory OAuth;
     SPF/DKIM/DMARC first.
6. Leads: pick ONE primary provider; keep the other behind the abstraction.
   Analysis-bound fetch, 90-day validity, stale warning, no bulk export.
7. Reports: **brief-first by default**; full Word on demand; both from
   `build_view`. Never drop the source line under each figure or the "limits"
   section.
8. Year handling: user never inputs a year; auto-select latest complete
   `data_year` per source; attach trend/CAGR to scoring; display the year under
   every figure.

## Non-negotiable invariants (guardrails)

- **I1** No fabricated data, ever. Failure → `None`, logged, surfaced.
- **I2** Human HS confirmation stays supreme and is the only writer of
  `hs_confirmed_by_user`. Amended by owner decision 2026-08-08 (ADR-0009): the
  engine's STRICT `tier="auto"` verdict may commit `hs_code`, provenance-tagged
  `hs_auto_classified` — never over a human confirmation, never on ambiguity,
  and never from name-only evidence when unexamined label signals exist
  (engine lesson 79). Amended again the same day (ADR-0010): the engine's
  LLM-decisive verdict (`source="llm_decisive"` — explicit `decisive` claim,
  confidence + margin bar, structural gate, `SILK_HS_LLM_AUTO` kill switch)
  reaches `tier="auto"` and commits through the same tagged machinery. A human
  confirm/override clears the tag and wins.
- **I3** Human campaign-approval gate stays 3-layer (API + worker row-lock + DB CHECK).
- **I4** Global suppression checked at send; one-click unsubscribe; append-only
  audit log; suppression stays cross-tenant.
- **I5** Paid agents run only inside the deepen context; deepen context passed
  explicitly into Celery task payloads and re-established in the worker
  (contextvars don't cross processes). Regression test: a paid agent outside
  deepen returns `skipped(paid_agent_outside_deepen)`.
- **I6** Cold outreach never through a transactional ESP (SES/Resend = system email only).
- **I7** pandas never imported under `apps/` or `packages/silk_intel` — `etl/` only. CI-linted.
- **I8** Compliance: PDPL Art. 25, GDPR legitimate-interest for EU, CAN-SPAM
  basics. Consent/basis recorded per lead.
- **I9** Transit-port guard in world ranking: flag re-export hubs (AE, NL, SG,
  HK, BE) with a visible "transit hub" tag + score penalty; mirror-derived rows
  tagged "mirror data".
- **I10** Arabic RTL-first UI; all strings via next-intl (ar/en).

## The 3-stage world funnel

- **Stage 1 — screen the whole world locally (zero live calls):** one SQL query
  over a precomputed `world_trade` table refreshed by `etl/world_trade_sync.py`;
  transit-port guard (I9) applied here.
- **Stage 2 — shortlist ~15–20 countries:** budgeted live enrichment via
  `silk_data_layer` (World Bank, WITS tariff, PPP, trend); respect throttles and
  the ~500 req/day Comtrade budget; log spend per analysis.
- **Stage 3 — top 5 deep-dive:** full agent pipeline on the 5 finalists; free
  layers auto, paid layers via deepen per country.

Report shows the funnel: "Screened 190+ markets → shortlisted 18 → top 5".

## Phased plan (summary)

- **Phase 0 — scaffold & freeze** *(this milestone)*: monorepo layout; Repo B →
  `apps/`; Repo A → `packages/silk_intel`; one CI (lint + apps tests + engine
  tests + pandas guard); `make dev`/`make demo` offline on mocks; freeze
  originals. **Acceptance:** CI green incl. all engine tests; `make dev`+`make
  demo` work offline with no keys.
- **Phase 1** — unify storage & contracts; Postgres adapter behind
  `silk_storage`; Redis cache; wire Celery to `silk_intel` for HS resolve + rank;
  port the deepen `contextvars` guard into Celery task context (I5) + regression test.
- **Phase 2** — full pipeline on mocks + funnel Stage 1 + transit guard + UX
  (HS confirm screen, campaign approval screen); brief-first reports; auto-year.
- **Phase 3** — go live one key at a time (Anthropic → Comtrade → leads+ZeroBounce
  → Smartlead/OAuth with SPF/DKIM/DMARC first).
- **Phase 4** — harden & launch (monitoring, PDPL retention/erasure, deploy,
  onboard pilots, evaluate Meilisearch threshold).

## Definition of done

A factory user can, in the Arabic RTL web app: upload a product image, confirm
the proposed HS code, receive a brief-first report showing "world screened → top
5 countries" (sources, years, transit flags, multi-year trend), open per-country
competitor lists with observed prices and margin threads, generate a verified
lead list for a chosen country, review an AI-drafted outreach email in the
buyer's language, approve it, and see it sent and tracked — with every number
source-tagged, every send human-approved and audited, and the whole system still
bootable offline on mocks with `make dev`.

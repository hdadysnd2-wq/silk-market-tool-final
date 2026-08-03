# DECISIONS LEDGER

Authoritative. When `docs/SPEC-v2.md` and this file conflict, **this file wins**.
Every command reads this before acting.

---

## Settled decisions

### D-01 — B2 vs E1 (readability vs cost)
Undefined jargon = **blocking issue**. Review cycle 2 fires ONLY on a blocking issue.
We accept a temporary cost increase as the price of readability.
**Interim ceiling: $1.7** until Part E lands. The $1.5 target is measured only after E.
*Rationale: B2 demanded more review, E1 demanded less. Readability wins now, cost is
optimized later against a stable baseline.*

### D-02 — C2 vs E3 (scraper vs runtime)
The scrape job is **async and does NOT count** against the 10-minute budget.
8-minute hard timeout; if it doesn't return, fall through the C4 chain and declare
the gap. **The run never waits on it.**
*Rationale: an 8-min poll inside a 10-min ceiling leaves zero margin. Decoupled instead.*

### D-03 — C1 is a manual owner step
Claude writes the Railway console steps and **stops**. Commands C2–C5 do not open
until the owner confirms the service is live.
*Rationale: Claude cannot provision Railway. A command that can't self-close is not
a command.*

### D-04 — Baseline is measured before any change
Measured in Command #1 and frozen at `docs/BASELINE-2026-07-16.md`.
Every before/after compares against a **frozen** file, never a moving target.
Part E re-measures into `docs/BASELINE-post-BC.md` because B and C shift the baseline
legitimately.

### D-05 — No "one run proves everything"
Each command closes with **its own live artifact**. The final run is confirmation,
not first contact.
*Rationale: a single acceptance run at the end means every defect surfaces at once,
with no way to attribute it.*

### D-06 — Cost-cutting budgets are re-measured against the CURRENT combined output; a new model is priced in the SAME command
Command #6/E2 shrank the writer/analyst `max_tokens` in the name of cost while four
earlier commands (B1, C5, D2, D3) had each **added required output**. Nobody
re-measured the combined load, so the first run that populated all four at once
(honey/UK) overran the ceiling and fell back to the skeleton — the anti-fabrication
guard held (every section «غير متاح», zero invented numbers), but there was no report.
Two permanent rules (LESSONS #16, enforced):
1. **A token budget in any cost-cutting change is re-measured against the summed
   output requirement of ALL prior commands, not the requirement it was first sized
   for.** This holds for every heavy stage: the writer (`_WRITER_MAX_TOKENS`, whose
   continuation call takes the ceiling not the base) AND the analyst
   (`_ANALYST_MAX_TOKENS` — it emits D2's five intersections + SWOT and must not fall
   back to the single-mission default of 6000, or the intersections truncate to
   «دليل غير كافٍ»).
2. **A new model integration is added to the `silk_pricing` table in the same command
   that introduces it** — a routed model with no price is silently excluded from the
   displayed total (understating it) while still being billed.

**Reconciliation method (documented, so "displayed ≈ billed" is checkable, not asserted):**
displayed total `= Σ_model ( input_tokens×input_rate + output_tokens×output_rate +
cache_read×input_rate×0.1 + cache_creation×input_rate×1.25 )` over
`silk_context.record_llm_usage`'s per-model counter (`silk_pricing.estimate_cost_usd`).
It reconciles with the Anthropic console when: (a) every routed model is priced
(else it appears in `unpriced_models` + the ⚠ chip, and `complete=False`), and
(b) every HTTP-200 response is metered **including `stop_reason=max_tokens`
truncations** — a failed/truncated call still burns (and is billed for) its tokens,
so it must still be counted. Both are locked by
`tests/test_command6_regression_budget_and_pricing.py`. A residual gap after those
two hold points at an env-set model id outside the pricing prefixes — add its real
rate (never guess one: no-fabrication).

*Consequence: the ≤$1.5 target from D-01 is REFUTED for a full report. A full
narrative carrying all four blocks on the Opus writer legitimately costs more than
$1.5; the ~$3 the owner was billed is the honest cost of a complete report, not an
overcharge. The target must be re-baselined against a run that actually succeeds
end-to-end — which is the #6 live re-run gate.*

### D-07 — New data-sources integration (six owner sites)

**WAVE 0 triage (read-only).** Each owner-designated site was assessed for official
API + auth + rate limits + ToS on automated access. Findings and per-source verdict:

| # | Site | API? / Auth | ToS on automation | Verdict |
|---|---|---|---|---|
| 1 | ttd.wto.org (WTO Tariff & Trade Data) | **Yes** — WTO Timeseries API (`api.wto.org/timeseries/v1`), free **subscription key** (`Ocp-Apim-Subscription-Key`, register at apiportal.wto.org), rate-limited per plan | Automated access permitted **with a key** | **INTEGRATED-with-artifact** — `silk_wto_tariff.py`, primary in the tariff fallback chain (closes the WITS EU bilateral gap, e.g. NLD HS 080410). Key-gated: no key → declared gap, zero network. |
| 2 | imf.org (IMF DataMapper / WEO) | **Yes** — `imf.org/external/datamapper/api/v1`, **free, no key**, generous limits | Public JSON API, automation permitted | **INTEGRATED-with-artifact** — `silk_imf_agent.py`, GDP growth / inflation / current-account into risk + macro missions. |
| 3 | globalbusinessculture.com | No API (content site) | Copyright content — no bulk fetch | **SEARCH-BIASED** — `consumer_culture` preferred domain (site: bias, snippets + link only). |
| 4 | tradingeconomics.com | API is **PAID**; scraping **violates ToS** | **No** bulk-fetch/scrape | **SEARCH-BIASED (citation-level only)** — `risk_news` preferred domain; NEVER fetched/scraped. Noted here so no later command reaches for its API. |
| 5 | ccacoalition.org/ar/resources | No API (content/resources site) | Copyright content — no bulk fetch | **SEARCH-BIASED** — `customs_requirements` + `risk_news` preferred domain (environmental/climate-compliance angle, ◐ secondary). |
| 6 | data.albankaldawli.org | **Not a new source** — Arabic UI of the SAME World Bank DB already integrated via `api.worldbank.org` | n/a | **REJECTED as a data source (zero new data)** — reused only as the client-facing WB citation URL for Arabic readability (`public_source_url(..., arabic=True)`). |

**Contracts (all six follow the platform contracts — this is now a lesson, LESSONS #32):**
a new source is **gap-declared on failure** (never fabricates), **ops-logged**
(`record_service_failure`, appears in `/ops/last-errors`), **cached**
(`silk_cache.cached_get`), **agent-panel gated** (rides existing mission gating),
and **ToS-clean** (no scraping of copyright content; paid/keyed APIs degrade cleanly
without the key).

*Evidence bucket (LAW §2): **hermetic only** — the environment's network policy
blocks all external hosts (only package registries reachable), so live IMF/WTO
probes were impossible this session. WAVE 0 findings are `static code review` +
public-API-documentation knowledge, not `direct reproduction`. Lock-tests validate
each parser against a **recorded response shape**
(`tests/test_wave_datasources_integration.py`); the live-shape confirmation is a
pending owner/deploy step, not claimed here.*

---

## Execution order (gated — do not skip ahead)

| # | Command | Scope | Closing gate | Status |
|---|---|---|---|---|
| 1 | Triage & baseline | read-only | Report + frozen BASELINE + ledger updated | ☑ 2026-07-16 — `docs/BASELINE-2026-07-16.md` + ledger below + report in PR |
| 2 | UI cleanup | A1–A3 | Zero orphan strings (grep pasted) + live UI: 2 actions + sidebar | ☑ 2026-07-16 — grep 0 orphans (prod) + live `GET /`→200, runbar 2 buttons + `#histList` |
| 3 | Assembly defects | D1–D3 | 3 green lock-tests + live run excerpts pasted | ☑ 2026-07-16 — lock-tests b1(9)/d2(6)/d3(5) green; excerpts in PR; suite 1068 pass |
| 4 | Merchant language | B1–B3 | Green lock-test on md AND docx + glossary pasted | ☑ 2026-07-16 — `test_merchant_language_b3.py` (5) md+docx green; glossary in PR + regenerated sample; suite 1073 pass |
| 5a | Scraper: owner steps | C1 | Steps written + clean-disable wired + owner confirms service live | ⏳ 2026-07-16 — steps (`docs/DEPLOY_SCRAPER.md`) + clean-disable (`silk_gmaps.py`, `/health`) + lock-test done; **awaiting owner: deploy 2nd service + confirm live (D-03 gate)** |
| 5b | Scraper: integration | C2–C5 | Importer table w/ real contacts + path printed + `/health` survives kill | ☑ 2026-07-16 — table renders md+docx (sample), path logged, kill→gap test green; **live real-contacts run is owner-side (scraper on private net, unreachable from CI)**; suite 1093 pass |
| 6 | Cost & speed | E1–E3 | ≤ $1.5 + < 10 min printed + prior lock-tests still green | ☒ **NOT DONE (regressed)** 2026-07-16 — E1/E3 stand; **E2's per-stage `max_tokens` budget was set below the combined output of B1+C5+D2+D3** (each a prior command that added required output) → first live run (honey/UK) failed the narrative («بلغ التوليد الحدّ الأقصى للطول», skeleton held, zero fabrication). The **≤$1.5 was never reconciled against real billing**: displayed $0.39 vs owner-billed ~$3 with a ⚠ «unpriced models» warning. Fix (Command #6-regression): writer first-attempt 8000→16000, ceiling 16000→32000, continuation call now takes the **ceiling** not the base; pricing/metering hardened + reconciliation method documented. **The ≤$1.5 target is REFUTED for a full report** — a full narrative with all four blocks on Opus legitimately costs more; re-baseline pending owner's live run. |
| — | Final run | confirmation | All 6 acceptance items with artifacts + **live narrative success with reconciled cost** | ☐ — blocked on #6 live re-run (see D-06) |

**Ordering notes:**
- #3 precedes #4 deliberately — both touch the render path. Fixing fact-loss first
  prevents building the style contract on a broken foundation.
- #6 is last — B and C legitimately change the baseline. Optimizing before them
  measures nothing.
- If #3 blows up, split it: D2 alone, then D1 + D3. Don't fight the context window.

---

## Scope discipline

Out-of-scope findings are **logged here, not fixed**. Standing instruction to Claude:

> This is outside the current command's scope. Log it as a note in the ledger and
> continue within the defined scope.

### Out-of-scope findings log

| Date | Found during | Finding | Belongs to |
|---|---|---|---|
| 2026-07-20 | Report-quality-upgrade self code-review (#3) | `TrendsAgent._execute` now always appends a `value=None` seasonality DataPoint when Trends returns no series — required so 2.2's gap+closure reaches the view, but it adds one extra `○ unverified` to `_client_confidence_section`'s tally on every trends-less report. **Kept as-is** (declaring the gap is the correct no-fabrication behavior vs. the old silent drop); follow-up: consider excluding pure closure-suggestion DataPoints from the evidence tally so the confidence % isn't diluted by a non-datum. | Confidence-tally refinement (future) |

---

## Item status ledger

Two states only: **DONE-with-artifact** or **NOT DONE**. No third state.

Triage note (Command #1): at triage time nothing had been fixed — Command #1 is
read-only, so every SPEC item started **NOT DONE**, with the evidence column
recording the current `file:line` state and any partial scaffolding from prior
PRs. Rows flip to **DONE-with-artifact** only as each later command lands its
live proof (e.g. A1–A3 closed by Command #2).

| Item | Status | Evidence (path / grep / URL / printed output) | Date |
|---|---|---|---|
| A1 | DONE-with-artifact | Feature deleted by #107 (module/endpoint/button gone); Command #2 removed the leftover orphan strings. Prod grep (excl tests/docs) «معاينة فورية» = 0, `snapBtn`/`quickSnapshot`/`products/snapshot`/`silk_snapshot` = 0. `tools/acceptance_run.py` step 6 (live POST to deleted `/products/snapshot`) removed. Stale `test_r4` `.pyc` deleted. `product_snapshots` table kept dormant (no-delete-silk.db rule), comment de-named. | 2026-07-16 |
| A2 | DONE-with-artifact | Exact button label «حلّل السوق» reworded off `silk_market_analyst.py:162` docstring (→ «التحليل الشامل للسوق»). Prod grep (excl tests/docs) exact «حلّل السوق» = 0. «مسح الأسواق» kept `web/index.html:251,316`; legit verb uses («حلّل سوق تصدير», chat examples, STOP-word) untouched. Enforcement tests keep the phrase as absence-guards. | 2026-07-16 |
| A3 | DONE-with-artifact | Live `GET /` → 200: runbar serves exactly TWO action buttons — `researchBtn` «بحث عميق» (primary) + `runBtn` «مسح الأسواق» (secondary); `id="snapBtn"` absent from served page; `#histList` sidebar present. Guards: `tests/test_ui_action_buttons_have_purpose.py`, `tests/test_item3_analyze_screen_button.py` green. | 2026-07-16 |
| B1 | DONE-with-artifact | Versioned contract `silk_style_contract.py` (`WRITER_STYLE_CONTRACT` injected into `silk_ai_judge.deep_report`; `GLOSSARY`/`SAR_PEG`). Deterministic pass `silk_render._apply_merchant_language` glosses each term on first use, contextualizes USD→SAR at the 3.75 peg, and emits a structured `glossary` rendered in md + operator docx + client docx. No-fabrication intact (annotates/contextualizes only). Regenerated `samples/research_report_latest.md` shows glossary + `HHI (…)` + «بسعر الربط». | 2026-07-16 |
| B2 | DONE-with-artifact | Reviewer prompt now flags any technical term/acronym without an Arabic gloss on first use as **blocking** (`silk_ai_judge.py` reviewer checklist + `blocking` JSON note), folded into the existing cycle (no extra paid cycle). | 2026-07-16 |
| B3 | DONE-with-artifact | `tests/test_merchant_language_b3.py` (5) locks glossary-present + no standalone HHI/CAGR/LPI/MFN at first use on **md AND docx** (client docx built and re-opened), + USD→SAR + no-fabrication. Green. | 2026-07-16 |
| C1 | NOT DONE (owner-gated, Claude-side complete) | Claude-side delivered: exact Railway console steps `docs/DEPLOY_SCRAPER.md` (2nd service from `gosom/google-maps-scraper`, own volume, private-networking-only), clean-disable `silk_gmaps.py` (`SILK_GMAPS_SCRAPER_URL`, empty=disabled) + `/health` informational status not gating `research_ready`, `.env.example` entry, lock-test `tests/test_gmaps_scraper_c1.py` (5) green, live `/health` toggle proof. **Remaining (D-03 owner gate): owner deploys the 2nd service + confirms live → then #5b (C2–C5) opens.** | 2026-07-16 |
| C2 | DONE-with-artifact | `silk_gmaps.submit_scrape_async` submits ONE job at run start (before missions, `api.py` `_run_research_pipeline`), localized queries `localized_queries` (NL→dadels/groothandel/halal groothandel/arabische supermarkt groothandel from `market_locale.csv`), depth 1 + email on, async poll with 8-min hard cap (D-02), collected with a short grace so runtime doesn't grow. Lock-test `tests/test_gmaps_integration_c2345.py`. | 2026-07-16 |
| C3 | DONE-with-artifact | `_parse_lead` (title/address/phone/EMAIL/website/rating/review_count/maps_link), `_dedupe` + `parse_and_rank` top-15, per-(market,query-set) cache `cache_get/put` reused across runs. No-fabrication: missing field → '', gap → []. Tests in `test_gmaps_integration_c2345.py`. | 2026-07-16 |
| C4 | DONE-with-artifact | Fallback chain `finalize_leads`: scraper → official Places (`silk_maps_agent.find_places`, name/address/rating, no email) → declared gap; `path` logged (`api.py` `gmaps leads path=…`). Kill test: scraper+Places down → gap, report intact. | 2026-07-16 |
| C5 | DONE-with-artifact | 7-col table «قائمة مستوردين وموزعين قابلين للتواصل» rendered md + operator docx + client docx from structured `view.deep_research.importer_leads`; `◐ مرصود عبر خرائط قوقل` level + disclaimer line («لا أنه يستورد التمور السعودية»); web candidates cross-matched/merged (`_merge_web_candidates`). Lock-test `tests/test_importer_leads_render_c5.py`; regenerated samples show the table. No-fabrication untouched. | 2026-07-16 |
| D1 | DONE-with-artifact | Closed by #107 + verified in Command #3. `silk_render._reconcile_mission_limits` retags a mission gap «حُسمت لاحقاً» only when a topic+number fact resolves it (else verbatim — no-fabrication); `_first_clause` gives the limits line the first sentence only (no mid-sentence «…»). Lock-tests `tests/test_limits_reconciliation_b1.py` (9) green. Live excerpt (reconstructed blob): limits show «حُسمت لاحقاً», zero «…». | 2026-07-16 |
| D2 | DONE-with-artifact | #107 shipped the diagnostics instrument but left the root fix NOT DONE. Command #3 adds a conservative synonym map (`silk_market_analyst._CATEGORY_SYNONYMS`) that rescues findings tagged with a category outside the literal 5 (e.g. `[pricing]`→price_competitiveness) — one of the three diagnosed causes; untagged findings stay diagnosed (nmt #8, no content-guessing). `diagnostics.synonym_rescued` surfaces drift. Lock-test `tests/test_analyst_synonym_rescue_d2.py` (6) green. Live excerpt: 5 synonym-tagged findings → all 5 intersections populated, synonym_rescued=4, missing=[]. | 2026-07-16 |
| D3 | DONE-with-artifact | Fetch was already fixed; the gap was writer-mapping (§9 relied on the `risk_news` LLM calling the tool for all 3 WGI). Command #3 adds deterministic augmentation `silk_missions._augment_risk_news_wgi` (all 3 incl. RL.EST which even RiskAgent omits) wired into `run_all_missions`; declared-gap on failure (no fabrication); §9 writer instruction updated to cite the attached `[risk]` facts `silk_ai_judge.py:918`. Lock-test `tests/test_wgi_governance_augment_d3.py` (5) green. Live: offline fetch → 3 declared gaps (None/0.0), no fabrication. | 2026-07-16 |
| E1 | DONE-with-artifact | Closed by #107, verified: `SILK_MAX_REVIEW_CYCLES` default 1, cap 2 (`silk_ai_judge._max_review_cycles`); cycle-2 rewrite fires **only on blocking** (`:1217`); B2 jargon-blocking feeds it. Retries bounded. Lock-test `tests/test_wave6_report_writer.py` (default-1 / blocking-triggers-cycle-2 / non-blocking-doesn't). | 2026-07-16 |
| E2 | ☒ **NOT DONE (regressed → refixed)** | The routing itself is right (missions→Haiku `silk_llm_runtime._MISSION_MODEL`, analyst/writer→`_SMART_MODEL` Opus, both **priced** in `silk_pricing`). **But the per-stage `max_tokens` budget was set below the combined required output** of the four prior commands (B1 glossary+glosses+SAR, C5 importer table, D2 five intersections, D3 WGI) — starving the narrative on the first run where all four populated together (honey/UK): writer hit the 16000 ceiling, the continuation call took the **base 8000** not the ceiling, the tail couldn't finish → `report=None` → skeleton. And the **≤$1.5/<10min «DONE-with-artifact» was never reconciled against real billing** (displayed $0.39 vs owner-billed ~$3 + ⚠ unpriced). Refix in Command #6-regression (`_WRITER_MAX_TOKENS` 8000→16000, `_MAX_TOKENS_CEILING` 16000→32000, `_continue_truncated_report` → ceiling; **analyst `_ANALYST_MAX_TOKENS` 6000→12000** so D2's five intersections don't truncate to «دليل غير كافٍ»; guard test that every routed model is priced; metering + reconciliation locked). Lock-tests `tests/test_command6_regression_budget_and_pricing.py`. **Cost target re-opened — see D-06.** | 2026-07-16 |
| E3 | DONE-with-artifact | Per-stage wall-time `data_economics.stage_seconds` {missions/analyst/synthesis/writer} + `stage_total_seconds` + labeled `stage_top_sinks` (top-3) in `api._run_research_pipeline`. Missions already concurrent; scrape decoupled (D-02). Lock-test `tests/test_cost_speed_e.py::test_stage_seconds_and_top_sinks_in_data_economics`. ≤$1.5/<10min are owner-printed live (`docs/BASELINE-post-BC.md`). | 2026-07-16 |

---

## Open questions (from triage)

| Q | Answer | Resolved |
|---|---|---|
| Which mission calls `google_maps` today? If none → "configured-but-unused" | **None.** No `/research` mission has a maps/places tool — full tool vocabulary in `silk_missions.py` `allowed_tools` + runtime registry `silk_llm_runtime.py:143-406` has no `find_places`. `/health` shows "on" purely on key presence `api.py:315-317`. Only the OLD `/analyze` path uses it (`silk_engine.py:164-165,470-471`; `silk_research.py:395,650`). **Verdict: configured-but-unused** (matches `docs/PLATFORM_ANALYSIS.md:173`). | ☑ |
| `/products/snapshot` — any internal callers? | **None.** Route defined `api.py:1675` and calls `silk_snapshot.quick_snapshot` at `api.py:1719` only inside that endpoint. No other module imports `silk_snapshot`. External callers: frontend `web/index.html:465,484`, acceptance harness `tools/acceptance_run.py:253`, tests only. → A1 may delete the endpoint + UI (module has no other consumer). | ☑ |
| `"…"` truncation — storage or renderer? | **Both.** Assembly/STORAGE: `silk_llm_runtime._truncate_at_word` `:648-658` via `silk_market_analyst.py:140,215` (summary capped at 3000 before store/writer). RENDER: `silk_reports.py:81-92` (`_clean_report_text`, default 300). Both retreat to word boundary (mid-word bug fixed) but still append "…". | ☑ |
| WGI — mission-fetch bug or writer-mapping bug? | **Writer-mapping bug.** Fetch is FIXED + lock-tested (`silk_data_layer.py:382-385,412-444`; `tests/test_technical_mission_failures_item2.py:39,58,76`). §9 has no deterministic binding of stored WGI facts — the writer prompt sources §9 from the `risk_news` mission's own findings `silk_ai_judge.py:918-921`, so numeric PV.EST/RL.EST + جودة التنظيم are absent when the mission doesn't surface them. | ☑ |

---

## Report Quality Engine Upgrade (زبدة الفول السوداني/اليمن — تدقيق المالك التحريري)

**Principle (LESSON #32): engine fixes over report edits.** Every editorial defect
family becomes a writer-contract rule + a deterministic view-layer enforcement + a
lock-test against a production-shape reproduction blob (`tools/canonical_yemen.py`) —
never a hand-edit of one report. All rows below are **hermetic-only** (rung 1 green);
the end-to-end **live regeneration** (correct HS family via the new gate + measured
tone/length + clean exports) is the owner's paid gate (LAW §2 bucket 2), pending.

| Item | Status | Artifact (file:line / test) |
|---|---|---|
| 1.1 Verdict badge==body (AI-first single source) | DONE-with-artifact (hermetic) | `silk_render.py` `_deep_research_view` v_raw AI-first; `test_report_quality_upgrade.py::test_w1_1_verdict_badge_matches_body_verdict` |
| 1.2 HS pre-flight confirmation gate (discriminating terms) | DONE-with-artifact (hermetic) | `silk_hs_confirm.confirm_hs`; `api.py` /research 422 gate behind `SILK_HS_CONFIRM_GATE`; tests `test_w1_2_*` (classifier + gate + no-fabrication). **Image-intake path: NOT DONE** (gate covers text /research; product-intake wiring deferred). |
| 1.3 Invalidated-numbers reframe + confidence cap | DONE-with-artifact (hermetic) | `silk_render._deep_research_view` (single `CONTEXTUAL_TAG` note + `SILK_HS_FLAGGED_CONF_CAP`); writer reframe rule; `test_w1_3_*` |
| 2.1 Stale-data inline tag + `SILK_STALE_DATA_YEARS` | DONE-with-artifact (hermetic) — **redesigned to provenance-based (owner decision, LESSON #33)** | Staleness decided at the fact (`silk_staleness.fact_year`/`is_stale_fact`/`stale_fact_years` from `data_year`/`year=YYYY` marker/`retrieved_at`); tagged at the writer choke-point `silk_ai_judge._facts`; render tags the **stale-fact-year list** anywhere via `silk_render._tag_stale_years(text, stale_fact_years)` (regex demoted to conservative backstop) + `_stale_tag_misses` verification. Closes review findings #1/#2/#3/#5 in one design. `test_w2_1_*` (provenance, phrasing-independent, HS-2008-safe, food-word-safe, choke-point, verification). **Round-2 review fixes (owner decisions):** (#2) stale-tag verification miss routed off client `limits`; (#3) observation-date fallback; (#4) era-suffix at word boundary; (#5/#6) import hoisted, redundant scan removed. **Round-3 — structured `data_year` field (owner decision, the permanent design):** vintage is now a first-class `DataPoint.data_year` field set by ALL collectors (`silk_data_layer._world_bank_for_year`, `silk_llm_runtime._tool_comtrade_imports`, `silk_market_ranker` Tier-1/Tier-2, `silk_data_layer_v2._competitor_dp`); `fact_year` reads the field first (the `year=` note-embedding is **retired** everywhere, kept only as a legacy READ fallback for old stored blobs); `retrieved_at` fallback widened to any past-year `YYYY-MM-DD` observation date while excluding the current-year fetch stamp; a belt-and-suspenders client sanitizer strips any residual `year=\d{4}`. Result: client md **and** docx carry no `year=`; vintage read from `data_year` across WB+Comtrade+competitor; the `year=` client-docx leak (prior finding #1) is closed. `test_w2_1_vintage_from_structured_data_year_field_not_prose`, `_collectors_set_data_year_field_no_year_marker`, `_wb_collector_sets_data_year_and_no_year_marker`, `_observation_date_widened_non_dec31_and_fetch_stamp_excluded`, `_client_surfaces_strip_residual_year_marker`. |
| 2.2 Seasonality gap declared once + closure step | DONE-with-artifact (hermetic) | `silk_trends_agent.SEASONALITY_GAP_CLOSURE` + `silk_render._has_seasonality_gap`; `test_w2_2_*` |
| 2.3 Weak-trends auto-broaden to category family | DONE-with-artifact (hermetic) | `silk_trends_agent.broaden_if_weak` (data-driven related term); `test_w2_3_*` |
| 3.1 Per-row price reason + single unlock | DONE-with-artifact (hermetic) | `silk_render._price_row_reason` + `PRICE_UNLOCK_LINE`; `test_w3_1_*` |
| 3.2 HHI context-only under flagged code | DONE-with-artifact (hermetic) | `silk_render` `concentration_context_only` + conf cap; `test_w3_2_*`. (Ranker /analyze HHI-score exclusion out of Yemen /research scope — noted.) |
| 4.1 De-duplicate HS warning (≤1 full note) | DONE-with-artifact (hermetic) | single `CONTEXTUAL_TAG` in limits + writer «انظر الملاحظة المنهجية»; `test_w4_1_*` |
| 4.2 Canonical section order | DONE-with-artifact (hermetic) | `silk_ai_judge._REPORT_SECTIONS`; `test_w4_2_*` |
| 4.3 Length budget (~30% tighter) | DONE-with-artifact (hermetic, contract) | `silk_style_contract.TARGET_TIGHTEN_PCT`/`PROFESSIONAL_TONE_RULE`; `test_w4_3_*`. **Measured word-count delta: owner live-regen gate.** |
| 5.1 Anti-alarmist tone + reviewer flag | DONE-with-artifact (hermetic) | Rule text `silk_style_contract.py:69` `PROFESSIONAL_TONE_RULE` (prepended to `WRITER_STYLE_CONTRACT` `:80`); banned list `:52` `ALARMIST_PHRASES` (3 examples + close variants incl. «يجب التوقف فوراً»); measured alt `:60` `MEASURED_TONE_HINT`. Deterministic reviewer enforcement in the **existing cycle, non-blocking** `silk_ai_judge.py:1188` `_alarmist_issues` → `:1278` `issues = structural + tone + llm`, reviewer-prompt line `:1250`. Tests `test_w5_1_reviewer_flags_alarmist_tone_as_nonblocking_issue`, `test_w5_1_measured_tone_draft_has_no_alarmist_issue`, **`test_w5_1_yemen_narrative_free_of_banned_phrases_and_rule_in_contract`** (Yemen narrative carries none of the 3 banned phrases nor variants). Deterministic before/after proof pasted in the exec report. **Live writer-tail regen: still owner's paid gate** (no ANTHROPIC key in CI sandbox — `available()==False`; keys live in Railway env, one-click). |
| 5.2 Sentence-length guidance | DONE-with-artifact (hermetic) | `silk_style_contract.py:66` `SENTENCE_MAX_WORDS=25` + `:73` «فضّل الجُمل القصيرة؛ الجملة التي تتجاوز خمساً وعشرين كلمة تُقسَم»; reviewer flags run-ons `silk_ai_judge.py:1252` («جُمَل مسترسِلة تتجاوز ~٢٥ كلمة»). Guidance-level, no hard char-count gate (per order). Test `test_w5_2_sentence_length_guidance_present`. |
| 6.1 Structured flip conditions + roadmap link | DONE-with-artifact (hermetic) | `silk_render._flip_conditions` (`view.flip_conditions`), rendered md + operator docx; writer roadmap-link rule; `test_w6_1_*` |
| 6.2 Exec-summary cap (verdict+flips+3 nums+3 risks) | DONE-with-artifact (writer contract) | `silk_ai_judge` deep_report 6.2 rule; `test_w6_2_*`. **Export length-cap enforcement + measured: owner live-regen gate.** |
| FINAL — live end-to-end regeneration | NOT DONE (owner paid gate) | Requires live server + paid writer tail. All engine fixes hermetic-green; regenerated committed samples updated (§10.6). |

---

## Final polish (live acceptance 2026-07-20) — § leak + IMF/WTO deep-research serve

### Item 1 — last "§" on the client report → CLOSED-with-artifact
**Symptom (live):** report.md line ~73 + client docx carried «قرار حتمي قابل للتفسير من حزمة **§4b** المتحقَّق منها …» — internal section notation on the client face (same family as the earlier §8 leaks, M-9).
**Root (file:line):** deterministic decision strings — `silk_decision.py` `note` (§4b) and critical-risk `why` (§8), plus `silk_render.py` decision `stage` (§8). The existing §-guard (`test_no_section_glyph_in_client_facing_strings`) only scanned `web/index.html`, so rendered report surfaces slipped through.
**Fix:** three source strings de-§'d (silk_decision `note`/`why`, silk_render `stage`); belt-and-suspenders client sanitizer rule `§[\w.]+ → ""` in `silk_reports._CLIENT_SANITIZE` (catches any stored-blob/model-echoed §); samples regenerated (§10.6) → `grep -c § samples/analysis_latest.json` = 0.
**Lock-tests (`tests/test_analyze_persistence_and_glyph.py`):** `test_no_section_glyph_in_rendered_analyze_report` (hermetic engine run → report.md + render_docx §-free), `test_no_section_glyph_in_deep_research_client_surfaces` (md + client docx §-free even with an injected §-note), `test_client_sanitizer_strips_section_glyph_token`. Any future § on a client surface fails CI.

### Item 2 — IMF WEO + WTO TTD on the deep-research path → OWNER-VERIFY (wiring hermetically proven)
**Trace (file:line):** `imf_indicator` tool (`silk_llm_runtime._tool_imf_indicator:285` → `silk_imf_agent.imf_indicator`) is in `MISSIONS["demographics_economy"].allowed_tools` (silk_missions.py:145) and `MISSIONS["risk_news"].allowed_tools` (:253) — both **run only in `/research`**, so `/analyze` quick-scan correctly never invokes IMF (expected, not a bug). Tariff: `wits_tariff` tool (`_tool_wits_tariff:271` → `silk_tariffs_agent.tariff_with_fallback:189`) runs the chain **WTO TTD → WITS → declared gap** and logs `tariff path=wto|wits|gap` (silk_tariffs_agent.py:204-218); wired to `MISSIONS["tariffs_agreements"]` (:191).
**Hermetic wiring lock (`tests/test_imf_wto_deep_research_wiring.py`, 5 tests):** tool declared to the missions + registered in `TOOLS`; `_tool_imf_indicator` reaches the IMF agent with the market; `_tool_wits_tariff` prefers WTO, falls to WITS, then to a declared gap (no fabrication). Wiring cannot silently break.
**NOT live-proven** (no paid run in CI — LAW §2). **Owner live-run checklist:**
1. `POST /research` with `{product:"تمر سكري فاخر", market:"Netherlands", hs_code:"080410"}` (correct HS family; ~4-min paid run).
2. **IMF served** — in the report's risk (§9) / macro section, look for GDP-growth / inflation / current-account figures each tagged **source «IMF WEO» + year**. In the API result, `deep_research.missions.risk_news.findings[*]` / `.demographics_economy.findings[*]` carry `source="IMF WEO"` with `data_year`.
3. **Tariff source** — the applied-tariff line served by **WTO TTD** (source «WTO TTD») or the honest fallback; confirm which via the server log `tariff path=wto|wits|gap` for HS 080410.
4. **/ops confirmation** — `GET /ops/last-errors` shows a `service_failure` row only if a source failed; `data_economics.live_fetches` counts the live calls. A `tariff path=gap` log with a declared-gap tariff line = both sources unavailable (honest, not fabricated).
Do not mark IMF/WTO "live-proven" until step 2–3 are observed on a real run.

---

## The Watchdog ("كاميرا مراقبة") — permanent owner-only monitoring (2026-07-21)

**Order.** Following the Kuwait-report stabilization (PR #134 — HS gate + cross-market leak
fixes, LESSONS 35–37), the supervisor requested a standing monitoring agent: watch every
`/analyze` and `/research` run, catch what the three Kuwait bugs would have caught automatically,
and report it in a **separate, owner-only surface** — zero contamination of any client deliverable.

**Prerequisite verified:** `#134` is merged into `main` (commit `b16ef6d`); the shared choke-point
(`silk_hs_confirm.preflight_block`, called from both `/analyze` and `/research`) exists and the
watchdog rides the same two call sites via `api._attach_watchdog`.

**Insertion point (smallest change).** Exactly two call sites in `api.py` — `_attach_watchdog(result, analysis_id, kind)`
called once at the end of `/analyze` (after `result["view"] = _view(result)`) and once inside
`_run_research_pipeline` right after the existing `_attach_quality_gate` call — mirroring the
established Wave-10 quality-gate pattern (`_attach_quality_gate` is already extracted for the
exact same reason: called from both the full `/research` run and the standalone report-regen
endpoint without duplicating logic). No pipeline re-routing; the watchdog hangs off the same
post-view choke-point every prior gate already uses.

| Part | Status | Evidence (path / test) |
|---|---|---|
| PART 1 — sensor layer | DONE-with-artifact | `silk_watchdog.py::observe`/`_observe_unsafe` — deterministic checks (hs_gate, badge/body, cross-market leak via `silk_storage.checkpoint_market_iso3s`, vendor/§/placeholder leaks reusing `silk_reports._client_sanitize`+`_client_forbidden_hits`, stale-tag consistency, price-sanity retail<wholesale, no-fabrication contract, quality-gate verdict, economics bands, mission failures, tariff path from finding `.source` not log-scraping, service failures via `silk_ops_log` time-window). Zero LLM calls (verified: no `silk_llm_runtime`/`silk_ai_judge` import in `silk_watchdog.py`). Stored in `watchdog.db`, independent of `silk.db`/`ops_errors.db`/`usage.db`. |
| PART 2 — separate report (owner-only) | DONE-with-artifact | `GET /watchdog` (JSON: badge/records/trend), `GET /watchdog/report.md` (standalone downloadable file, both key-protected like `/ops/last-errors`); `web/index.html` sidebar entry `#watchdogNav` → dedicated view `#v-watchdog` (structurally separate from `#v-board`/`#v-input`, never rendered inside an analysis view — locked by `tests/test_watchdog.py::test_web_ui_watchdog_entry_is_a_separate_view_not_inside_analysis`); each record carries `analysis_id` for one-way linkage (analysis never references the watchdog — locked structurally: `silk_render.py`/`silk_reports.py` never import `silk_watchdog`). |
| PART 3 — trend brain | DONE-with-artifact | `silk_watchdog.trend_report()` — on-demand aggregation (no cron) over the last N records: cost/duration trend (first/last/avg), contract-violation rate, advisory rate, WTO-vs-WITS fallback rate, service-fallback count; rendered as a section of `render_report_md()`. `KNOWN_OPEN_BACKLOG_NOTE` states the H-1..H-9 open-backlog count so the report always distinguishes monitored vs. known-and-open. |
| PART 4 — self-protection | DONE-with-artifact | `observe()` never raises (internal `try/except` around `_observe_unsafe`, returns a `self_error`-carrying yellow record on any internal failure, mirrors "الحارس تعطّل في التشغيلة X" wording); `api._attach_watchdog` wraps the call in its own `try/except` as a second layer; watchdog never blocks/slows a run (no return value consumed by the caller, pure side-effect write); measured overhead ~8ms/run (`test_observe_adds_negligible_latency`, printed). |

**Lock-tests (`tests/test_watchdog.py`, 29 tests):** seeded cross-market violation → red; clean run
→ green; watchdog internal crash → isolated (`self_error`, never raises, analysis result untouched);
zero watchdog strings reach `render_markdown()`/exported client surfaces; all three known
service-failure kinds (`scraper`/`trends`/`imf`) each produce the correct yellow finding; `observe()`
never mutates the `result` dict passed to it (confidentiality-by-design, same principle as vendor-name
redaction, LESSON 18); API endpoints return records/badge/trend and require the key when configured;
`_attach_watchdog` call-count structural guard (≥3, same pattern as the HS-gate choke-point check).

**Evidence bucket (LAW §2):** hermetic only — `python3 -m pytest tests/ -q --ignore=tests/test_r3_trends_context.py`
green (1434 passed, 17 skipped, plus the 29 new watchdog tests). No real-server/browser (rung 2/3) run
in this sandbox; the sidebar UI wiring is source-verified (grep-locked), not click-tested live. Owner's
next real run should confirm: `GET /watchdog` after a live `/research` run shows the new record with the
correct badge, and the sidebar "تقرير الحارس" entry renders the table in a live browser.

`docs/LESSONS.md` row 38 added (same-session, test-first per the self-update protocol), anchored in
`tests/test_regression_registry.py::_guard_watchdog_owner_only_no_client_contamination` and
`tests/test_lessons_enforcement.py`.

---

## The general-purpose HS classifier — the systemic fix (2026-07-21)

**Order.** After the Kuwait-report stabilization (#134) and the watchdog build, the supervisor
identified the *root* problem behind the peanut-butter/dairy-butter misclassification: the resolver
is a static, partial CSV lookup table — it will keep failing on every unusual product forever (rose
water, flavored chips, oud incense…), not just the one reported instance. Two structural changes
+ the UI dialog, framed explicitly as "a lookup table is a starting hint, never the decider."

| Part | Status | Evidence (path / test) |
|---|---|---|
| PART 1 — general-purpose resolver | DONE-with-artifact | `silk_hs_classifier.classify_general()` — deterministic-first (zero LLM calls when the CSV seed already gives a strict, unambiguous match, e.g. "تمور"→080410); on cache-miss + genuine ambiguity, ONE Haiku call (`_claude_classify_general`) asks the model for its top-3 HS6 candidates **from its own full-nomenclature knowledge**, not constrained to our CSV. Every candidate (deterministic or LLM-sourced) passes the SAME validation gate (`_validated_candidate`): chapter-sanity against `silk_hs_resolver.VALID_HS_CHAPTERS` (the real WCO chapter structure, 01–97 minus withdrawn 77 — a structural constant, not a product/ISO hardcode) + discriminating-term overlap via `silk_hs_confirm.confirm_against_description` (a new shared core, `_overlap_stats`, factored out of the existing `confirm_hs` so both paths use one comparison, not two that could drift). Three explicit outcome tiers: `auto` (strict — top candidate ≥0.8 overlap, verified against our reference, AND a clear margin over the runner-up — genuine ambiguity between two candidates never auto-passes), `candidates` (a 422/advisory carrying up to 3 ranked, validated candidates), `manual` (nothing defensible — raw CSV rows as a manual-picker starting point only, never a confident suggestion). Cached per normalized product name in `silk_store` (new `hs_classify_cache` table, migration `004_hs_classify_cache.sql`) — repeat products cost zero extra calls (`silk_hs_classifier._reserve_llm_call` self-meters, count+dollar, right before the one real network call — not speculatively on every flagged request). |
| PART 2 — UI confirmation dialog | DONE-with-artifact | `web/index.html`: `showHsCandidates(detail, cb)` replaces the old single-proposal `showHsProposal` — one dialog function reused for BOTH `/classify_hs` (pre-flight, `ensureHs()`) and the `hs_confirmation_needed` 422 from `/analyze` **and** `/research` (both previously unhandled for `/analyze`; `preflight_block` now attaches `candidates` to its blocking response, computed by the exact same `classify_general()`). Candidates render as clickable cards (code + Arabic description + one-line reason + a "✓ من مرجعنا"/"اقتراح" grounding badge) plus manual-entry and cancel. The auto-classified checkmark ("✓ صُنّف تلقائياً") is structurally impossible to render on a 422 — it only appears in `ensureHs()`'s own `tier==="auto"` branch, never inside the dialog. `/analyze`'s `buildBody()` now sends `hs_code`/`hs_confirmed` (it sent neither before). |
| PART 3 — regression battery | DONE-with-artifact | `tests/test_hs_general_classifier.py::_BATTERY` — 10 product families (peanut butter, rose water, cheese-flavored chips, sukkari dates, sidr honey, oud incense, roasted salted nuts, chili sauce, specialty roasted coffee, zamzam-style bottled water) parametrized against their acceptable HS2 chapter set. Contract asserted for all 10, **with the LLM unavailable** (worst case — deterministic resolver alone): if tier reaches `auto`, the chapter MUST be in the acceptable set, or the run fails loudly — no silent wrong-chapter auto-pass is tolerated regardless of AI availability. A second parametrized pass (5 of the harder products) mocks realistic LLM candidates and asserts the correct chapter surfaces in the top-3 even when the deterministic seed alone would have produced junk (e.g., "شيبس بنكهة الجبن" lexically matching "بن" — coffee — via a substring-containment quirk in the pre-existing `_covered()` heuristic; caught and confirmed non-auto-passing during this battery's construction). |

**Real gap found and fixed during construction (documented, not silently patched):** the first draft of
`_validated_candidate` matched only the CSV row's own description when the code was in our reference —
several reference rows carry English-only descriptions (`name_ar=""`), so a correct Arabic-named product
scored a hard 0.0 overlap against a code that was semantically exactly right (`200811`, prepared
groundnuts, English-only in our seed) purely because the two texts were in different scripts. Fixed by
taking the better of (CSV description) vs. (model-supplied description + its stated reason) per candidate
— `verified` still reflects whether the code is structurally grounded in our reference, independent of
which description won the term-overlap check.

**Playwright/e2e-live-shape (rung 3):** `tests/e2e/hs_candidates_flow.cjs` + `test_rung3_playwright_e2e.py::
test_rung3_hs_candidates_dialog_blocks_on_flagged_product_and_never_auto_badges` — a real headless-chromium
run against a real uvicorn server, product name injected via a minimal test-only hook
(`window.__silkTestSetProduct`, since "زبدة الفول السوداني" is deliberately absent from the product-search
index — that absence is exactly why it needs this gate) confirms: the dialog blocks with at least one real
candidate, the auto-checkmark text never appears in it, and picking a candidate closes the dialog and sets
the confirmed badge to the chosen code. Existing `prerun_flow.cjs` / `readiness_flow.cjs` updated in the
same PR — they previously asserted the OLD single-proposal `#hsOk` modal always appeared for "تمور", which
the new strict-auto tier now correctly skips (no dialog for a clean, unambiguous match) — both re-verified
green against a live server in this session.

**What is NOT live-proven here (LAW §2, bucket 2/3 boundary):** e2e-live-shape strips `ANTHROPIC_API_KEY`
deliberately (same policy as every other rung-3 test, so CI never fires a real paid call) — the candidates
shown in the e2e run above are deterministic-CSV-only. Confirming that a live Claude call surfaces `200811`
specifically for "زبدة الفول السوداني" (the literal acceptance-criteria example) is the owner's live,
keyed run — `tests/test_hs_general_classifier.py`'s mocked-LLM tests hermetically prove the mechanism
handles that response correctly, which is the strongest claim obtainable without spending real money in
this session.

`docs/LESSONS.md` row 39 added (same-session, test-first), anchored in
`tests/test_regression_registry.py::_guard_general_hs_classifier_no_lookup_table_ceiling` and
`tests/test_lessons_enforcement.py`.

## UI-ONLY FIX — tier consumption, the two real bypass paths (2026-07-21)

**Order.** The supervisor filed a live bug report: `/classify_hs` is proven correct for all product
families, but the frontend ignores its `tier` verdict — specifically naming `ensureHs` (~line 646) as
reading only `res.hs6` and unconditionally marking "✓ صُنّف تلقائياً" regardless of tier.

**What was verified against `origin/main` before touching anything:** `ensureHs()` was already correct
— it branches on `res.tier==="auto"&&res.hs6` before setting `S.hsConfirmed`/showing the checkmark,
and this exact branch shipped with e2e proof in the general-classifier PR immediately above. The cited
symptom does not reproduce against the merged code as described. Rather than rewrite already-correct
code to match an inaccurate root-cause claim, a full structural audit (every site in `web/index.html`
that writes to `#pResolved`) was run to find what *actually* bypasses the tier gate — the owner's
underlying concern (a second path trusting `hs6` blindly) turned out to be real, just in two different
places than named.

| Gap found | Status | Evidence |
|---|---|---|
| `#pDrop` (product-search dropdown row click) | FIXED | Set `S.hs`/`S.hsConfirmed=true` directly from the raw catalog index code with zero validation — same trap as "زبدة"→040510 if a lexically-close-but-wrong row is ever indexed. Now routes through `ensureHs()` when the classifier flag is on (unchanged fallback when the flag is off — the common/default deployment state). |
| `#intakeGo` (image-intake confirm button) | FIXED | Resolved via a raw `GET /resolve/{name}` call, bypassing the classifier entirely for extracted-from-photo product names. Now routes through `ensureHs()` — same choke point the typed-name path uses. |
| `resolvedAs` shared i18n string | FIXED | A second-order form of the same bug class, found while writing the structural guard test: the shared badge-text translation key literally baked in `"✓ صُنّف تلقائياً — رمز HS "` — so *every* consumer of `t("resolvedAs")` displayed the auto-classified checkmark, including manual candidate-pick (`showHsCandidates`'s `commit`), full manual entry (`showHsManual`'s `commit`), and the classifier-disabled `#pDrop` fallback. None of those are auto-classified. `resolvedAs` is now neutral (`"رمز HS: "` / `"HS code: "`); the checkmark text is now a literal string owned exclusively by `ensureHs`'s `tier==="auto"` branch. |

**Structural guard (single choke point):** `"✓ صُنّف تلقائياً"` now occurs exactly once in
`web/index.html` — inside `ensureHs`, gated by `res.tier==="auto"`. Enforced three ways: a hermetic
text-scan test (`tests/test_wave1_hs_classifier.py::test_web_ui_never_shows_auto_badge_from_unverified_source`),
a matching registry guard (`tests/test_regression_registry.py::_guard_ui_tier_consumption_single_choke_point`),
and a real-browser parametrized lock-test
(`tests/test_rung3_playwright_e2e.py::test_rung3_ui_tier_consumption_locked_across_product_families`,
driving `tests/e2e/hs_tier_family_flow.cjs`) that runs six real product families through one live
session: "زبدة الفول السوداني"/"مياه ورد"/"عود معطر"/"زيت زيتون" must show the candidates dialog and
never the checkmark; "تمر سكري"/"عسل سدر" must show the checkmark with no dialog.

**Honest deviation from the owner's literal example list (LAW §2):** the owner's live evidence used a
keyed environment where "زيت زيتون" resolved `tier="auto"`. e2e-live-shape strips `ANTHROPIC_API_KEY`
by policy (same as every other rung-3 test), so in this keyless sandbox `classify_general("زيت زيتون",
allow_claude=False)` returns three CSV candidates (150910/150990/071120) too close together to clear
the auto margin — the lock-test places it in the `dialog` group instead of `auto`. This is the
fail-safe working as designed (uncertain → ask, not guess) on a plausible product name that lacks a
structurally-verifiable deterministic margin, not a regression — documented here rather than silently
adjusted to match the owner's exact grouping. `تمر سكري`/`عسل سدر` were independently confirmed to
auto-pass deterministically (no LLM) and are used for the `auto` group instead.

Full suite (1468 passed / 18 skipped) and rung-3 Playwright e2e (4/4, `full_browser` excluded per its
pre-existing unrelated sandbox failure) both green in this session. `docs/LESSONS.md` row 40 added
(same-session, test-first), anchored in
`tests/test_regression_registry.py::_guard_ui_tier_consumption_single_choke_point` and
`tests/test_lessons_enforcement.py`.

## ONE FIX — the classifier must actively resolve, not echo a rejected code (2026-07-21)

**Order.** Owner report: for "زبدة الفول السوداني" the dialog correctly *rejects* the lexical match
040510, but then offers only "إدخال رمز يدوياً" / "إلغاء" — a dead end for a merchant who does not
know HS codes and must never be asked to type one. Requested: one behavior change — when the
deterministic lookup rejects its match, the classifier must actively invoke the existing LLM path,
validate the result through the same gate, and return it as the **primary** one-click candidate.
Explicit scope discipline: no new UI surfaces, guards, or paths — reuse the existing dialog and
LLM/validation code.

**Root cause (two compounding bugs in `silk_hs_classifier.classify_general`'s existing mechanism —
the LLM-invocation trigger itself was already correct and already fired; the bug was in what happened
*after*):**

1. `_rank_key` sorted candidates `(verified, overlap, model_confidence)` — `verified` (mere presence
   in our partial CSV reference) as the *primary* key. A wrong-but-in-our-table deterministic guess
   (e.g. 040510, `verified=True`, weak overlap) could rank above a correct LLM-proposed candidate that
   happened not to be in our partial reference, or lose a near-tie it should have won — the exact
   `lookup-table-ceiling` family (LESSONS row 39) leaking into *candidate ordering* rather than the
   auto-tier gate that row 39 already closed.
2. `silk_hs_confirm._covered()` (the shared discriminating-term overlap core) allowed containment
   matches on roots as short as 2 characters. Reproduced live: for "شيبس بنكهة الجبن" (cheese-flavored
   chips), the 2-letter root "بن" (coffee) is a literal substring of both "بنكهة" (flavored) and "جبن"
   (cheese) — a coincidental collision, not a real semantic match — inflating the wrong deterministic
   candidate 090111 ("بن غير محمص", unroasted coffee beans) to overlap 0.67, *beating* the correct
   LLM-proposed 200520 (potato chips) at 0.33. This is why the mechanism's own regression battery
   (`test_battery_llm_assisted_surfaces_correct_chapter_when_deterministic_weak`) never caught it — that
   test only asserted the correct chapter *appeared somewhere* in `candidates`, never that it was
   `candidates[0]` (the one-click primary).

**Fix (`silk_hs_classifier.py` + `silk_hs_confirm.py`, both minimal, no new surfaces):**

| Change | What it does |
|---|---|
| `_rank_key` | Now `(passes_min_overlap_gate, source=="llm", overlap, model_confidence)`. A candidate that clears the same discriminating-term gate everything else must clear ranks above one that doesn't, regardless of origin. Among gate-passers, an LLM-sourced candidate — invoked specifically *because* the deterministic-only result was rejected — outranks a deterministic one on a lexical-overlap tie (a coincidental tie should not defeat an actively-verified semantic conclusion). `_clearly_auto`'s explicit `verified` requirement for the strict `auto` tier (LESSONS 39) is untouched — this only changes which candidate leads the `candidates` tier's one-click list. |
| `_covered()` | Containment matches now require the shorter of the two compared roots to be ≥3 characters (`SILK_HS_CONFIRM_MIN_CONTAINMENT_LEN`, default 3) — exact-equality matches remain unconstrained by length. Kills short-root coincidences (2-letter Arabic roots collide inside unrelated longer words disproportionately often) without weakening genuine matches (verified against the existing `confirm_hs`/`_validated_candidate` test suite — all still pass, including the exact "زبدة"/040510 whole-word match the original incident depended on). |

**Breadth proof, not a peanut-butter patch.** `tests/test_hs_general_classifier.py::
test_breadth_active_resolution_surfaces_correct_primary_not_rejected_or_blank` — parametrized over the
owner's literal 8-family list (زبدة الفول السوداني، مياه ورد، عود معطر، شيبس بنكهة الجبن، قهوة عربية
محمصة، صلصة شطة، مكسرات محمصة مملحة، لبان مستكة), each with a realistic mocked Claude response,
asserts `candidates[0]`'s HS2 chapter is in the acceptable set for every one of the 8 — no family
needed a declared-gap exception; the two-bug fix above generalizes cleanly across all 8, not just the
original incident's product.

**Env honesty (LAW §2, bucket 2/3):** the active-resolution step needs `ANTHROPIC_API_KEY` +
`SILK_HS_CLASSIFIER=1` live. The breadth test mocks `silk_ai_judge._call` (a recorded/realistic Claude
response shape) to prove the mechanism hermetically — dedup/ranking/gate logic, not the live model
call itself. Confirming the *literal* live Claude response for each of the 8 products is the owner's
keyed environment; this session proves the pipeline handles a correct LLM answer properly once one
arrives, which is the strongest claim obtainable without spending real money here.

Full suite (1469 passed / 19 skipped) green in this session. `docs/LESSONS.md` row 41 added
(same-session, test-first), anchored in
`tests/test_regression_registry.py::_guard_active_resolution_beats_rejected_and_short_root_collision`
and `tests/test_lessons_enforcement.py`.

---

## جلسة 2026-07-23 — دقّة تصنيف HS (عائلة الزبدة) + الكتابة الأكاديمية افتراضياً

### D-22 — الـresolver يُخفّض الرمز مغلوطَ العائلة إلى فجوةٍ معلَنة (لا رمز خاطئ واثق)

**الحادثة (إعادة إنتاج حيّة، طلب المالك «افحص دقّة اختيار الكود»):**
`resolve('زبدة الفول السوداني')` كان يُرجع `040510` (زبدة **ألبان**) بثقة 0.85 —
نفس عائلة الحادثة الأصلية (الدرس ٣٢/٣٩). الجذر: في `silk_hs_resolver._score` يمنح
الشرط `k in q` درجة 0.85 حين تكون كلمةٌ مفتاحيةٌ **عامّة** («زبدة») مُتضمَّنةً في
اسمٍ مركّب، بينما صفةُ المنتج المميّزة («فول سوداني») غائبةٌ عن وصف الرمز.

**الإصلاح (إصلاحان، كلاهما بلا شبكة/اختلاق):**
1. **بيانات** — الرموز الصحيحة الموجودة أصلاً في البذرة (`200811` فول سوداني محضّر،
   `180400` كاكاو، `151590` شيا) زُوِّدت بكلماتٍ مفتاحيةٍ عربية فصارت قابلةَ الوصول
   وتفوز بتطابقٍ تام (`data/hs_codes.csv`). لا رمزٌ مُختلَق — كلها موجودةٌ بأوصافها
   الرسمية، أُضيف مدخلُها العربي فقط.
2. **منطق** — `silk_hs_resolver.resolve_all` يعيد استعمال `silk_hs_confirm.confirm_hs`:
   مرشّحٌ أعلى تطابقاً لكن `confirmed=False` (صفتُه المميّزة غائبةٌ عن وصفه) يُخفَّض
   إلى **فجوةٍ معلَنة** (`value=None، ثقة 0.0`) بسببٍ صريح، لا رمزٌ خاطئٌ واثق. يحرس
   العائلة كلها لا الزبدة وحدها. التأكيد `None` (لا وصف/لا صفات) لا يُخفِّض (فشلٌ آمن
   مفتوح). **حدّ معروف:** عتبة التأكيد 0.5 تعني أن مركّبات كلمتين قد تمرّ؛ التصادم
   الحقيقي (فول سوداني، ٣ كلمات، تداخل 0.33) يُخفَّض، والمنتجات الحقيقية مُغطّاة
   بالإصلاح البياني.

**الأثر على الحادثة:** «زبدة الفول السوداني» تُحسَم الآن تلقائياً للرمز **الصحيح
200811** بلا أيّ نداء كلود، والرمز الخاطئ 040510 ينزل لمرشّحٍ ثانويٍّ بثقة 0.33.
حارس الدرس ٣٩ السلوكي حُدِّث ليقفل القاعدة الدائمة («الرمز الخاطئ لا يفوز أبداً»)
بدل الافتراض المُبطَل («البذرة بلا مرشّحٍ صحيح»).

**الأقفال:** `tests/test_hs_butter_family_resolution.py` (٦ أقفال) +
`tests/test_hs_general_classifier.py::test_classify_general_never_auto_passes_flagged_product_without_llm`
(الاسم مرساةٌ ثابتة، الجسم شُدِّد) + `tests/test_regression_registry.py::_guard_general_hs_classifier_no_lookup_table_ceiling`.

### D-23 — الكاتب يكتب أكاديمياً افتراضياً في مسار /research (طلب المالك)

**الاكتشاف:** البنية الأكاديمية كانت متاحةً فقط عبر التصدير/إعادة التوليد
(`?style=academic`)؛ أمّا التوليد الرئيسي (`_run_research_pipeline` →
`write_reviewed_report`) فكان يستدعي الكاتب **بلا `style`**، فيستعمل العقد التجاري
دوماً — فحتى التصدير الأكاديمي كان يعيد تشكيل نثرٍ كُتب بسجلٍّ تجاري.

**الإصلاح (`api.py`):** التوليد الرئيسي يمرّر النمط للكاتب في المسارين المتزامن
والخلفي؛ الافتراضي «academic» عبر `SILK_REPORT_STYLE` (قابلٌ للضبط: `commercial`
يعيد السجل التجاري)؛ وقيمةٌ صريحة في الطلب (`report_style`) تتقدّم على البيئة؛
والنمط المستعمَل يُخزَّن في `deep_research.report_style` لاتّساق العرض/التصدير.
العقد الأكاديمي يحفظ كل قواعد الصدق/العملة — السجل اللغوي وحده يتغيّر.

**الأقفال:** `tests/test_academic_writer_default.py` (٦ أقفال توصيل نصّي) بالإضافة
للأقفال القائمة في `tests/test_academic_report_style.py`.

---

## جلسة 2026-07-23 (تابع) — البند أ٢: فحص معقولية بلد المورّد

### D-24 — إشارةٌ اقتصاديةٌ مُعاضِدةٌ لتأكيد رمز HS (خلف صمّامٍ مطفأ)

**السياق:** توقيع المالك على مذكّرة التصميم `docs/DESIGN_A2_SUPPLIER_PLAUSIBILITY.md`
(البند أ٢ من Issue #144). بوّابات تأكيد HS القائمة نصّيةٌ فقط؛ لا شيء يقارن
موردي السوق الفعليين بما يجب أن يبدو عليه ملفُّ مصدّرٍ معقولٍ للرمز — فرمزٌ خاطئٌ
لكنه نصّياً معقولٌ يعبرها (حادثة زبدة الفول السوداني/الألبان: أيرلندا/نيوزيلندا
تتصدّران 040510).

**التنفيذ:** `silk_market_ranker.supplier_plausibility(hs, market_iso3, m49, year)`
يقارن مجموعتين من كومتريد حيّ (صفر نداء مدفوع، صفر ISO/HS مكتوب صلبًا):
موردو السوق الفعليون (`market_imports().competitors` → ISO3) وأكبر مصدّري الرمز
عالميًا (`top_world_exporters`). تفكّكٌ ≤ `SILK_A2_MAX_OVERLAP` (افتراضًا 0.0:
تفكّكٌ تامٌّ) + كلا الطرفين ≥ `SILK_A2_MIN_ENTRIES` (3) => `implausible`. تعذّرُ
القياس/بياناتٌ هزيلة => `None` (صمت، فشلٌ آمن مفتوح). موصولٌ في بوّابة `/research`
كتحذيرٍ حاجب (422 حتى `a2_ack`) وفي لوحة الجاهزية كفحصٍ استشاري. خلف صمّام
`SILK_A2_PLAUSIBILITY` **مطفأ افتراضيًا** => السلوك كاليوم حتى يعايره المالك حيًّا.

**تنقيحٌ عن المذكّرة (§٣٫١) مُعلَنٌ صراحةً:** المذكّرة اقترحت الإطلاق على الدرجات
**غير التلقائية** فقط؛ التنفيذ يُطلق على **كلّ رمزٍ** (خلف الصمّام) لأنّ (أ) درجةُ
التصنيف غير متاحةٍ عند بوّابة ما قبل التشغيل بلا إعادة تصنيف، و(ب) قيمةُ أ٢ الفريدة
هي بالضبط ضبطُ رمزٍ يعبر البوّابات النصّية لكنه اقتصاديًا خاطئ (شقيق حادثة الألبان
حين يعبر النصّ). مخاطر الإيجابيات الكاذبة مضبوطةٌ بالفعل بعتبة التفكّك التامّ +
حدّ البيانات الأدنى + كونه تحذيرًا حاجبًا لا رفضًا. المالك يضيّق النطاق عبر
`SILK_A2_MAX_OVERLAP`/`SILK_A2_MIN_ENTRIES` عند الحاجة.

**الأقفال:** `tests/test_a2_supplier_plausibility.py` (١٠ أقفال: تفكّك→implausible،
تداخل→plausible، بيانات هزيلة→None، فشل قياس→None، عتبات env، لا ISO/HS صلب،
بوّابة 422 حتى الموافقة، صمّام مطفأ لا يُطلق).

---

## جلسة 2026-07-23 (تابع) — البند هـ: فرض البنية الفرعية لأقسام التقرير

### D-25 — حارسٌ حتميٌّ غير حاجب للبنية الفرعية داخل قسم التوصيات

**السياق:** البند هـ من Issue #144 (المذكّرة المدموجة `docs/DESIGN_E_SECTION_SUBSTRUCTURE.md`).
`_section_order_issues` كان يفرض العناوين الأحد عشر وترتيبها **فقط**؛ البنية
الفرعية داخل القسم غير مفحوصة — قسمٌ بعنوانٍ صحيح قد يخلو من العناصر التي
يطلبها موجّه الكاتب.

**التنفيذ (المجموعة ١-٣ فقط — العناصر المطلوبة أصلًا في الموجّه):**
`silk_ai_judge._section_substructure_issues(draft)` فحصٌ حتميٌّ (لا كلود)
مقيَّدٌ بنافذة قسم التوصيات (`_section_window`، الدرس ٤٢: فحص النافذة لا كامل
المستند)، يتحقّق من: (أ) خارطة دخولٍ ٩٠ يومًا، (ب) فرع «شرطا قلب الحكم» حين
يكون الحكم مشروطًا/مراقبة (§6.1). **غير حاجب (WARN)**: يُضاف إلى `issues` (يُعلَن
في «حدود هذا التقرير») لا إلى `blocking` (لا دورة تنقيح مدفوعة إضافية) — مكمّلٌ
**مستقلّ** لطلب المراجع النثري (لا يعتمد على انتباه النموذج وحده، الدرس ٤٢).
**خلف صمّام `SILK_E_SUBSTRUCTURE_CHECK` مطفأ افتراضيًا** (نظير `SILK_A2_PLAUSIBILITY`):
المراجعة الذاتية عبر الحزمة كشفت أنّ تفعيله الفوري يُطلق تحذيرًا كاذبًا على قسمٍ
يعلن فجوةً مشروعة (بلا خارطة) — وهو بالضبط ما حذّرت منه المذكّرة §٥ (لا حارس بلا
معايرةٍ حيّة). فالمنطق يُشحن مُختبَرًا، ويُفعَّل بقرار المالك بعد معايرة معدّل
التحذير على نثرٍ حيّ.

**النطاق المؤجَّل صراحةً (المذكّرة §٥):** إضافةُ عناصرَ **جديدة** لموجّه الكاتب
(SWOT كمُخرَج، جداول مؤشرات كلّية/شرائح مستهلك، فجوة سعرية صريحة، قنوات مرتّبة،
تكميم مراحل الاستراتيجية — المجموعات ٤-٨) لم تُنفَّذ: المذكّرة تشترط قياسًا حيًّا
مسجّلاً (`mission-tuning-and-evals`) يؤكّد إنتاج الموجّه للعنصر **قبل** لمس الموجّه
أو إضافة حارسه، وهو خارج نطاق الساندبوكس بلا مفتاح. المدوّنات القانونية نصُّ
تقريرها فارغٌ (يولّده الكاتب الحيّ)، فالمعايرة على نثر النموذج الحقيقي (معدّل
التحذير الكاذب) تبقى بيئة المالك المفتاحية. الأقفال هنا تثبت **منطق** الحارس
حتميًا على عيّناتٍ نصّيةٍ مصنوعة.

**الأقفال:** `tests/test_e_section_substructure.py` (٩ أقفال: بنية كاملة→صفر،
مشروط بلا بنية→تحذيران، GO لا يتطلب قلب الحكم، القسم الغائب صامت، نافذة القسم
محترمة، الوصل غير الحاجب في review_report).

# Silk Market-Intelligence — Full Platform Analysis

> **Method & honesty note.** This document was produced by a read-only sweep of
> the live code, tests, and docs (no live or paid runs; the dev environment has
> no keys and the network is gated). Every factual claim is anchored to
> `file:line` or a named test. Where a number is an estimate or a score is a
> judgment, it is labelled as such. Written for two readers at once — an engineer
> and the business owner — so each section leads with plain language and drops to
> `file:line` for the engineer underneath.
>
> **On the baselines this analysis "re-grades against."** The commissioning brief
> refers to four prior artifacts — a *10-criteria client-readiness rubric*, external
> scores of *idea 9 / engineering 9 / product 7.5*, a *3-strong / 7-adequate / 2-weak*
> mission scorecard, and a *Phase-3 sellability assessment*. A full search of `docs/`
> found **none of these committed to the repository** — they live in a prior external
> conversation, not in the tree. Rather than pretend to re-grade against something
> that isn't here, this document (a) quotes the closest committed analogues, (b)
> constructs a defensible rubric/scorecard from committed material, and (c) states
> plainly where a score is a fresh judgment rather than a delta.
>
> Snapshot: branch `claude/platform-analysis-mciijc`, HEAD `f40463d` (PR #83),
> 2026-07-14. Measured directly: **52 Python modules, 92 test files, 880 tests**,
> CI = `python -m pytest tests/ -q` (`.github/workflows/ci.yml`), 5 pinned deps
> (`requirements.txt`).

---

## Executive summary (one page — business language)

**What it is.** Silk is a market-intelligence engine for Saudi exporters. Ask it
about a product and it ranks ~38 world markets and produces a sourced entry study;
ask it to go deep on one market and it runs a 12-mission AI research pipeline and
writes a consultancy-style Arabic report. Two more surfaces wrap that core: a cheap
"is this product worth a full study?" snapshot, and a grounded chat over any finished
study. The whole thing is built on one hard rule — **it never invents a number.**
Every figure carries its source, and every gap is declared out loud rather than
filled with a guess. That rule is not a slogan; it is enforced in code and locked by
tests.

**Where it stands.** The engineering is genuinely strong and unusually disciplined:
880 hermetic tests, a single canonical view that every output derives from, a
structural paid/free boundary, defense-in-depth sanitization, and a fabrication-free
data contract that held through every recent change (`evals/golden_cases.json` is
still an honest `[]`). The product has also grown real reach in the last dozen PRs —
a client-vs-operator report split, a competing-products price table, quick snapshot,
and grounded chat, all shipped with tests the same day.

**The honest gap.** Two things separate "an impressive, honest tool" from "a study a
paying factory would sign a cheque for," and both are known and tracked, not hidden:

1. **The differentiating intelligence — verified named buyers and verified shelf
   prices — is paid-gated.** The free deep-research path can only ever produce
   *unverified web candidates*, and it correctly tags them so. Verified buyers come
   from Volza and structured prices from SerpApi/Google-Shopping, both behind the
   paid `/deepen` layer and both requiring keys the current environment doesn't have.
2. **Nothing has been verified against a real live run.** Every test cuts the
   network; the flagship samples are explicitly *simulated* fixtures; there is no
   golden eval case; and the one recurring production failure — the report writer
   timing out and returning no report — is **still unresolved** (instrumented and
   waiting for the next live failure, deliberately not guessed at).

**The verdict, in one line.** A rare thing: an AI product whose main risk is *not*
that it makes things up (it structurally can't) but that it hasn't yet been proven at
full strength in production, and that its most sellable data sits behind a paid switch
nobody has flipped and measured. The single highest-leverage next action is to
**provision the paid keys and execute one fully-instrumented live `/research` run
end-to-end** — that one action simultaneously reproduces (or clears) the writer bug,
exercises the paid sellable-data path, and creates the missing live baseline and first
golden sample.

**Updated headline scores** (external baseline was 9 / 9 / 7.5; see §7 for
justification and the caveat that the baseline is uncommitted):

| Dimension | Score | One-line justification |
|---|---|---|
| **Idea** | **9 / 10** | Real, under-served need; honest-by-construction is a genuine differentiator in a category full of confident fabrication. |
| **Engineering** | **9 / 10** | Invariants enforced structurally and guard-tested; 880 hermetic tests; stdlib-first discipline. Held back only by the total absence of live-integration testing. |
| **Product execution** | **7.5 / 10** | Big feature breadth and consultancy-grade formatting landed — but the flagship deliverable has an unresolved production-failure mode, no live-verified output exists, and the sellable data is paid-gated. |

---

## 1. What the platform is today

### 1.1 Two pipelines on one spine (architecture refresher)

Everything runs through one canonical view-model and one verdict engine; the two
"pipelines" differ only in how they gather evidence before that point.

- **Pipeline 1 — `POST /analyze` (the free breadth path).** `silk_engine.analyze()`
  (`api.py:534`): resolve product→HS6 → rank ~38 markets on 4 weighted components →
  3 core agents on the top markets → optional `with_*` enrichment → optional
  correlation → `silk_synthesis.synthesize()` → `silk_render.build_view()`. It ranks
  markets; Claude is optional garnish. Structurally free-only (the request model has
  no paid fields).
- **Pipeline 2 — `POST /research` (the deep single-market path).**
  `_run_research_pipeline` (`api.py:775`): 12 Claude tool-use missions
  (`silk_missions.MISSIONS`, `silk_missions.py:50`) run in parallel →
  `silk_market_analyst.analyze_market` builds 5 mandatory intersections →
  the **same** `synthesize()` → `silk_ai_judge.write_reviewed_report` (writer+reviewer)
  → the **same** `build_view()`. It returns `markets:[]` plus a `deep_research` block
  (`api.py:848`); it does **not** rank markets. Claude is a hard requirement here (409
  preflight, `api.py:997`).
- **One view, one verdict.** `build_view` is the single view-model every surface reads
  from (dashboard, docx, brief, markdown, chat context). `synthesize()` is the only
  verdict entry point. These are architectural invariants (§3), not conventions.

**Documentation drift found:** the entire `/research` + client-report initiative is
absent from `CLAUDE.md`, `VISION.md`, and `EXECUTION_PLAN.md` (acknowledged as
out-of-plan scope at `docs/DEEP_RESEARCH_DECISIONS.md:9-16`). `docs/ARCHITECTURE.md`
is itself stale (written post-wave-11: it reports 626 tests / 21 routes / 62 files
vs. today's 880 / 24 routes / 52 modules). And the decisions ledger stops at wave 13
(637 tests) — the last ~8 PRs (#76–#83: Eurostat, mission-depth upgrades, client
report, R1 competing-products, chat, snapshot; ~4,000 LOC, 240+ tests) are **not**
recorded there. This is governance drift, not a code defect — flagged in §3/§6.

### 1.2 Feature inventory

Maturity key: **production-ready** = deterministic/offline logic with passing hermetic
tests (usually + a committed sample); **works-but-unverified-live** = logic + hermetic
tests exist but the real payoff needs a live Claude/paid call only ever mocked or run
against a *simulated* sample; **stub** = declared but empty.

| # | Feature | What it does | Where (file:line) | Maturity | Last verification evidence |
|---|---|---|---|---|---|
| 1 | **`POST /analyze`** | Rank ~38 markets, sourced entry study, free-only | `api.py:534`; spine `silk_engine.analyze` | **Production-ready** | Real-engine sample `samples/analysis_latest.json`; `test_m2_pipeline.py`, `test_smoke.py`. (Its stage-2 Claude judge is unverified-live.) |
| 2 | **`POST /research`** | 12-mission deep study of one market | `api.py:914`; `_run_research_pipeline:775`; `silk_missions.py` | **Works-but-unverified-live** | `test_wave6_research_api.py::test_full_mocked_run_reaches_stage2_and_writes_report` (**mocked**); only sample is *simulated* (`samples/README.md:14`). No captured live run committed. |
| 3 | **Client vs operator docx** (two-template split) | Default client report (7 sections, zero telemetry) vs full operator export via `?internal=1` | selector `api.py:1279`; `render_client_docx` `silk_reports.py:1694`; operator `_render_research_docx:1183` | **Production-ready** (as a render/guard layer) | `test_client_report_export.py` incl. `test_guard_rejects_export_when_forbidden_term_leaks`; samples `client_report_latest.docx` / `report_full_latest.docx`. Content only as live as its upstream. |
| 4 | **Operator dashboard + agent-settings panel** | Single vanilla-JS page; per-agent on/off + free-text command | `web/index.html`; `GET/POST /settings/agents` `api.py:623/642` | **Production-ready** | `test_agent_settings_panel.py`, `test_wave7_agent_panel_fallback.py`. UI tested by source-grep, not a rendered run. |
| 5 | **Chat / `/ask`** | One grounded Claude answer over one stored analysis, no agent re-runs | `POST /analyses/{id}/ask` `api.py:1372`; sanitized `api.py:1402` | **Works-but-unverified-live** | `test_p4_contextual_chat.py` (isolation, grounding, sanitization); `test_r2_chat_grounding.py`. No live-answer sample. |
| 6 | **Quick snapshot** (redesigned ITEM 2, live cost audit) | Free "worth a full study?" probe: Comtrade suppliers only, cached — the Claude `pricing_scout` call was removed entirely (never fires a paid call); competitor pricing is a declared gap on a never-snapshotted pair, upsold to `/research` | `POST /products/snapshot` `api.py:1653`; `silk_snapshot.py` | **Production-ready** (deterministic, no live call to verify) | `test_r4_product_snapshot.py` incl. `test_snapshot_never_calls_claude`. |
| 7 | **Competing-products scout / Saudi price positioning** (R1, #82) | ≥3-store price/kg table in market's language; exporter percentile position | mission `silk_missions.py:51`; positioning in client report `silk_reports.py:1802` | **Works-but-unverified-live** | `test_r1b_competing_products.py`, `test_rf_positioning_confidence.py`, `test_r1c_prose_pass.py`. Real price capture only in an anecdotal live run, not committed. |
| 8 | **Confidence index** | (i) verdict confidence phrase everywhere; (ii) client-report evidence-badge tally (✓/◐/○) | verdict `silk_render.py:38-55`; badges `silk_narrative.py:368`; tally `silk_reports.py:1510` | **Production-ready** | Deterministic. `test_rf_positioning_confidence.py::test_confidence_section_tallies_badges_correctly`. |
| 9 | **Reverse discovery `/discover`** | Given a market, rank HS opportunities (growth + Saudi-gap + seasonality) | `api.py:1112`; `silk_discovery.py:173` | **Production-ready** | `test_wave5a_discovery.py` incl. AST source-set guard + offline no-fabrication. |
| 10 | **`POST /deepen`** (paid path) | The only path that runs the 3 paid agents | `api.py:681`; `_guard_paid:692`; `deepen_context():694` | **Works-but-unverified-live** | Structural paid guard tested (`test_wave0_security.py`, `test_wave3_agents.py`). No live paid-provider verification in-repo (by design — keys only in Railway). |

**Full endpoint surface (24 routes, `api.py create_app()`):** `/health` (262),
`/resolve/{name}` (331), `/index` (340), `/markets` (349), `/analyze` (534),
`/settings/agents` GET/POST (623/642), `/settings/keys` (660), `/deepen` (681),
`/research` (914), `/research/{id}/status` (1078), `/discover` (1112), `/trend`
(1135), `/diagnostics` (1153), `/sources` (1174), `/analyses` (1210),
`/analyses/{id}` (1220), `/analyses/{id}/brief` (1235), `/analyses/{id}/report.docx`
(1252), `/report.md` (1296), `/analyses/{id}/report` regen (1315),
`/analyses/{id}/ask` (1372), `/products/snapshot` (1413),
`/analyses/{id}/outcome` PATCH (1484), static UI `/` (1508).

**Reading the maturity column honestly:** almost everything Claude-dependent is
"works-but-unverified-live" — the offline/degraded behaviour is production-ready and
tested, but the actual intelligence payoff has never been captured from a real run.
The deterministic features (analyze spine, discovery, confidence index, the render/
guard layer) are genuinely production-ready.

---

## 2. Data & intelligence assessment

### 2.1 Source coverage

Every wired source returns provenance-tagged `DataPoint`s; failure = `None` /
`confidence 0.0`, never a fabricated number.

| Source | Wired at | Feeds | Known ceiling |
|---|---|---|---|
| **UN Comtrade (direct)** | `silk_data_layer.comtrade_trade:277`; tool `silk_llm_runtime.py:143` | trade_flow, pricing unit-value, ranker size | **Keyless ≈ 4 calls/day** — starves under 38-market fan-out (prod: Trade 2/30 vs Economic 37/38, `SOURCE_AUDIT.md:36`). Needs `COMTRADE_API_KEY` (~500/day). Annual totals only. |
| **Comtrade mirror (PR #78)** | `comtrade_trade_mirror_total` `silk_data_layer.py:329` | Rescues size/shares for non-reporting markets | Fires only on empty-success, not fetch-failure; confidence capped **0.6**, tagged "(مرآة)". |
| **World Bank** | `world_bank:354`; tool `:253` | demographics, LPI, WGI/FX | Free & keyless — most reliable. WGI/LPI lag ≥1yr, LPI biennial. |
| **FAOSTAT** | `silk_faostat_agent`; tool `:323` | per-capita food supply | Auth wall (401/403 common); circuit breaker + `SILK_DISABLE_FAOSTAT`. Food HS only. |
| **Eurostat (PR #79)** | `silk_eurostat_agent.py`; tool `:387` | consumer_culture (EU food-spend, migrant size) | **EU/EFTA only**; table codes **unverified live** (docstring warns). |
| **GDELT** | `silk_gdelt_agent`; tool `:346` | risk_news headlines | Datacenter-IP WAF blocking on Railway; web fallback forced ≥5 headlines. |
| **Google Trends** | `silk_trends_agent`; tools `:277/:287` | demand_trends, consumer_culture | `pytrends` optional; **429 on cloud IPs is a known unfixable-in-repo ceiling**. |
| **OpenAlex** | `silk_openalex_agent`; tool `:356` | demand/risk/gaps (low-weight) | Always optional support, never primary. |
| **WITS tariffs** | `silk_tariffs_agent`; tool `:265` | tariffs_agreements | Volatile; below-MFN labelled "تفضيل محتمل — تحقق", not asserted. |
| **Web search (Serper)** | `silk_websearch_agent`; tool `:333` | prices, company names, culture, importers | **Only `serper` implemented** (serpapi/bing are TODO, `:57`); **snippet text only, no structured extraction**. |
| **Google Places/Maps** | `silk_maps_agent.py` | named businesses — **/analyze old path only** | Key-gated; not wired into /research. |
| **Volza (PAID)** | `silk_volza_agent.py` | verified named importers | Only *verified* buyer source; `/deepen` only, no call without key. |
| **LocalPrice/SerpApi Shopping (PAID)** | `silk_localprice_agent.py` | structured retail prices | Only *structured* price source; `/deepen` only. |

**The 5 source outages PR #72 fixed** — all guard-tested in
`tests/test_wave_p4_source_outages.py`: WITS Invalid_Reporter (numeric codes +
EU→918), WB WGI archived (source=3), Comtrade 429 (backoff+jitter+min-gap), FAOSTAT
401 (circuit breaker + kill switch), writer-failure silent logging (unconditional
error line). Mirror (#78) and Eurostat (#79) also tested
(`test_phase2c_a_mirror_statistics.py`, `test_phase2c_b_eurostat.py`).

**One collected-but-unread hole:** WGI/LPI/FX are pre-collected to the fact store
(`silk_collectors.py:106`) but `get_indicator` has **zero production callers** — the
Risk pillar consumer was never built (`SOURCE_AUDIT.md:20,43`). Data flows in and sits
unused.

### 2.2 The 12 missions — re-graded

Earlier external baseline: *"3-strong / 7-adequate / 2-weak"* (not committed to `docs/`;
closest committed artifact is the wave-8 mission performance card at
`DEEP_RESEARCH_DECISIONS.md:513-527`, which graded on a different "broken vs executed"
axis). Re-grade below reflects the state **after** PR #77 (Phase 2B depth upgrades).

| # | Mission | Tools | Budget | Re-grade | Why |
|---|---|---|---|---|---|
| 1 | pricing_scout | web, trends, comtrade, lookup | 9 | **adequate** ↑ | #77 added Comtrade unit-value line; retail prices still unverified snippets |
| 2 | consumer_culture | web, trends×2, lookup, openalex, eurostat | 9 | **strong** | richest tool set; fragile on Trends 429 |
| 3 | trade_flow | comtrade | 9 | **strong** ↑ | #77 forced explicit 5-yr + CAGR; real Comtrade (keyless-throttled) |
| 4 | demographics_economy | worldbank, lookup | 5 | **strong** ↑ | #77 wired a previously-dead youth% indicator; WB reliable |
| 5 | competitors | comtrade_competitors, comtrade, web | 9 | **strong** (country) / weak (firms) | shares+HHI always available; firm names unverified |
| 6 | customs_requirements | lookup, web | 5 | **adequate** ↑ | #77 added gap-declaration on empty; static CSV |
| 7 | tariffs_agreements | wits, lookup | 5 | **adequate→weak** | WITS volatility; agreements cover only the 38 markets |
| 8 | logistics | worldbank, lookup, web | 5 | **adequate** | LPI + ports CSV; **shipping cost is a declared gap** |
| 9 | channels_importers | channels, web | 9 | **weak** | all candidates unverified; verified only via paid Volza |
| 10 | demand_trends | trends×2, faostat, openalex | 9 | **adequate but fragile** | both hard sources (Trends, FAOSTAT) are the ones that get blocked |
| 11 | risk_news | worldbank, gdelt, web, openalex | 9 | **adequate→strong** | WGI+FX real; GDELT WAF-blocked but web fallback forced |
| 12 | opportunity_gaps | openalex | 5 | **adequate** (derivative) | no own data class; reads missions 1–11 as citable DataPoints |

**Re-grade tally: ~5 strong / ~6 adequate / 1 weak.** The needle moved **up** vs. any
"3/7/2" baseline, concentrated in the four PR #77 targets (trade_flow,
demographics_economy, pricing_scout, customs_requirements), which closed real
tool/instruction gaps (a dead indicator, a silently-3-year query, a discarded weight
signal, silence-on-empty). The single persistent **weak** is `channels_importers` —
no verified free source exists; it is structurally deferred to paid Volza.

### 2.3 Analyst & writer — after the rewrites

**The "5-intersection ceiling" is still exactly 5 required buckets** —
`REQUIRED_CATEGORIES = demand, entry_cost, price_competitiveness, entry_door, swot`
(`silk_market_analyst.py:30-31`) — but PR #76 changed what those 5 *are*. They went
from 5 canned pairwise formulas to **5 open-ended analytical mandates**:

- Core rule reversed to "analyze everything — there is no closed list of allowed
  relationships"; the 4 example formulas are now explicitly *"a floor, not a ceiling"*
  (`silk_market_analyst.py:49-63`).
- Cross-cutting obligations over all 5: triangulation/contradiction declaration,
  benchmarking, an explicit "so what for the Saudi exporter" per finding, and evidence
  weighting observed > estimated > gap (`:91-107`).
- A strict anti-"insufficient-evidence" rule: with ≥2 linkable facts, writing "دليل
  غير كافٍ" is banned — an explicit arithmetic calculation is forced (`:110-119`). This
  was the direct fix for the live bug where all 5 intersections read "insufficient"
  despite real data.
- Wiring fix: the analyst's real analysis now reaches the writer and the stage-2 judge
  via `_comprehensive_digest()` (`:123-140`) — previously it only reached the docx
  appendix (a ~700-char status line was all the writer saw).

The **writer** (`silk_ai_judge.deep_report:717+`) mirrors this at the prose layer: each
section cross-references all 12 missions; declares contradictions; benchmarks;
linguistically separates observed ("وفق UN Comtrade") from inferred ("تقديرنا
استناداً…"); adapts §7 to the HS chapter; and **explains the ready verdict, never
issues its own**. Empty sections are written with a declared gap, never deleted.

Net: the ceiling is now "5 mandatory lenses, each unbounded in depth," plus a
professional 11-section Arabic report above it. This is a real capability increase
over the original fixed-factor version.

### 2.4 The high-value-data problem — honest current state

**The two things that make a report actually sellable — verified named buyers and
verified transaction prices — are structurally behind the paid `/deepen` layer. The
free `/research` path can only produce unverified candidates, and it tags them so.**

- **Named importers:** free-path candidates come back at confidence **0.4** tagged
  *"مرشَّح من بحث الويب — غير مُتحقَّق"* (`silk_importers_agent.py:21-23,55`); the
  mission tags them *"غير موثَّقين — التحقق عبر التعميق"* (`silk_missions.py:210`).
  **Verified** names exist only from `VolzaAgent` (bills of lading), PAID, no call
  without `VOLZA_API_KEY`.
- **Verified prices:** free-path prices are Serper snippets; any price without a real
  store link is tagged *"◐ غير موثَّق"* (`silk_missions.py:70`). Automated numeric
  price extraction from snippets was **deliberately not built** — it would re-introduce
  the extract-numbers-from-free-text fabrication risk the Stage-5 review rejected
  (`SOURCE_AUDIT.md:154-159`, deferred item 2.1). Comtrade unit-value is a wholesale
  reference range, "لا سعر تجزئة فعلياً". **Structured** prices only from `LocalPrice`
  (SerpApi Shopping), PAID.

**The gap to "sellable."** The committed "sellable report" work is **Wave 9**
(`DEEP_RESEARCH_DECISIONS.md:541-657`). Read honestly, Wave 9 fixed **presentation** so
a report *looks* sellable — evidence badges instead of raw confidence, a mandatory
90-day roadmap, professional docx, zero leaks — and shipped a *simulated* fixture, not
a live result (`:654-657`). The **remaining data gap** is exactly the high-value-data
problem: the roadmap's entry-door candidates are ○ (unverified) and price positioning
leans on the product card, because verified buyers and prices are only obtainable
through paid providers. Closing it requires either (a) provisioning the paid keys
(`VOLZA_API_KEY`, `LOCALPRICE_API_KEY`, plus `COMTRADE_API_KEY`, `SEARCH_API_KEY` to
lift the free-path ceilings), or (b) building the deferred fabrication-safe retail-price
normalizer (item 2.1) — which is on hold precisely because no one has found a
normalization that doesn't risk inventing numbers.

---

## 3. Quality & safety posture

### 3.1 Test suite anatomy (880 tests, 92 files)

All hermetic — the network is cut at the socket layer by one canonical guard
(`tests/conftest.py::block_network`, which also closes the pooled HTTP session first);
fact store, trace dir, and the data-economics contextvar are isolated per-test by an
autouse fixture. Coverage map by layer:

| Layer | Key files |
|---|---|
| Data / no-fabrication core | `test_smoke.py`, `test_p0_wiring_and_confidence.py`, `test_year_fallback.py`, `test_phase2c_a_mirror_statistics.py`, `test_phase2c_b_eurostat.py` |
| Agents / paid boundary | `test_wave3_agents.py`, `test_agent_settings_panel.py`, `test_wave7_agent_panel_fallback.py` |
| Missions / runtime | `test_wave6_missions.py`, `test_wave6_llm_runtime.py`, `test_phase2b_mission_depth.py`, `test_wave_p0_prompt_caching.py` |
| Analyst | `test_wave6_market_analyst.py`, `test_stage3_*triangulation.py` |
| Writer / reviewer | `test_wave6_report_writer.py`, `test_stage5_*.py`, `test_wave_p1_ai_timeout_and_failure_reasons.py`, `test_wave_p2/p3_*.py` |
| Synthesis / verdict | `test_stage4_decision.py`, `test_p5_judge_and_reach.py`, `test_wave4_correlation.py` |
| Render / reports | `test_wave6_deep_research_view.py`, `test_report_professional_tables.py`, `test_client_report_export.py`, `test_wave9_sellable_report.py` |
| Sanitization / leaks | `test_report_plumbing_leaks.py` (30+), `test_wave_p3_writer_diagnostics_and_json_leak.py`, `test_p4_contextual_chat.py` |
| Security guards | `test_wave0_security.py`, `test_wave7_security_p0.py`, `test_diagnostics.py` |
| Quality gate | `test_wave10_quality_and_structure.py`, `test_wave12_architecture_audit.py` |
| Storage / persistence / resilience | `test_m1_store.py`, `test_persistent_volume.py`, `test_staleness_policy.py`, `test_wave13_resilience.py` (11) |

**The specific guards exist and are located:**
- **Forbidden-terms / prose-calque:** client docx raises `RuntimeError` if any
  telemetry term survives (`_client_assert_clean` `silk_reports.py:1352`) — loud
  rejection, not poisoned delivery; tested by `test_client_report_export.py`. Gulf-idiom
  prose pass tested by `test_r1c_prose_pass.py`.
- **Leak regression:** `test_report_plumbing_leaks.py` covers `dp7`/`LLMAgent:` /raw
  category tags / raw decimals / bare partner codes; raw-JSON leak by
  `test_wave_p3_*`.
- **No-fabrication assertion style:** canonical `assert dp.value is None and
  dp.confidence == 0.0` + note; `confidence == 0` appears across 17 test files
  (e.g. `test_smoke.py:341,361`).
- **AST architecture tests:** correlation zero-network
  (`test_wave4_correlation.py::test_acceptance_5_zero_external_calls_from_correlation`)
  and discovery zero-new-sources (`test_wave5a_discovery.py::test_acceptance_4_*`).
- **Single-authoritative-verdict:** `test_single_authoritative_verdict_everywhere` +
  `test_duality_removed_single_verdict_entry` (asserts `not hasattr(judge,
  "ai_verdict")`).

**What is NOT covered (the honest gaps):**
- **No live-integration test exists at all.** Every test cuts the network; the live
  Claude JSON-parsing / confrontation-prompt / true-E2E paths are unexercised by CI
  (`docs/ANALYSIS.md:176`). The one Playwright browser check (wave 13) was a one-off
  manual verification, not in the suite.
- **docx is asserted on extracted text, not bytes** — content is genuinely checked
  (paragraphs + table cells), but there's no rendering-fidelity assertion.
- **The frontend has no unit tests** (source-grep assertions only).
- **The eval harness has zero golden cases** (`evals/golden_cases.json == []`) — there
  is no automated live-accuracy baseline for any Claude-dependent feature.

### 3.2 Sanitization pipeline — end-to-end

Two canonical strip functions in `silk_render.py`: `_strip_raw_json_leak` (`:571`) and
`_strip_internal_plumbing` (`:648`, which chains JSON-strip → mission-key-prefix →
`LLMAgent:`/`dp7` regexes → English-field Arabization → bare-verdict strip →
note-humanization). **Every customer-visible text surface passes through it**, traced:

report text (`:903`), mission summaries (`:801`), analyst summary/reasoning
(`:818,847`), unresolved notes + failure_reason (`:855,857`), AI verdict note (`:882`),
consumer-culture insights (`:246`), market-dynamics SWOT/Porter/PESTEL (`:695,1034`),
enrichment competitor notes (`:968`), correlation threads (Arabic-only, declared gaps,
zero-network by AST), `/ask` answer (`api.py:1402`), and the **client docx** — which
derives from the already-sanitized view and then applies a **second** independent
sanitizer + a raising assert-guard (`silk_reports.py:1450,1352`). The writer's *input*
verdict was also de-leaked (Layer 4/9: `_summarize_verdict` replaced a raw
`json.dumps` dump that leaked `DataPoint` reprs).

Prompt-injection isolation is a distinct, additional layer: every external string into
Claude passes `silk_ai_judge._isolate()` — and the wave-12 audit closed the one real
hole (tool-output `value`/`source` were unisolated; now `_isolate_external` covers
them).

**Is any surface still bypassing? No.** No customer-visible text field was found
reaching `build_view` or a report without a strip. The only residual risk is
*definitional*: the strip is regex/dictionary-driven, so a novel leak token not yet in
the pattern set would pass — which is exactly why the quality gate re-scans output and
can elevate to FAIL (the Layer 7/9 "irony bug" fix). This is defense-in-depth working
as designed.

### 3.3 No-fabrication invariants — structurally verified (not assumed)

All five held through recent changes:

| Invariant | Verified at | Guard |
|---|---|---|
| DataPoint None-on-failure (malformed dropped, never zeroed) | `primary_value` `silk_data_layer.py:241`; `comtrade_trade` returns `None` on fail vs `[]` on no-record | `test_smoke.py:341,361` |
| Uncited LLM claims dropped | `_parse_output` `silk_llm_runtime.py:708-756` (valid_ids filter; unparseable never leaks raw) | `test_wave6_llm_runtime.py`, `test_wave_p3_*` |
| Inferred zero capped at 0.6 confidence | `silk_market_ranker.py:180-184`; mirror `silk_data_layer_v2.py:232` | `test_p0_wiring_and_confidence.py` |
| World/partner reconciliation (`max(world, partner-sum)`, >20% divergence flagged) | `market_imports` `silk_data_layer_v2.py:153-175` | `test_smoke.py::test_market_imports_missing_value_no_fabricated_zero_competitor` |
| `evals/golden_cases.json == []` | confirmed file content `[]` | `test_wave6_evals.py` |

### 3.4 Open issues

- **Writer-timeout case (PRs #69/#70/#71): STILL UNRESOLVED, instrumented-only.** The
  writer failed in three separate production runs; the three PRs fixed only what was
  provable (split timeout `SILK_AI_LONG_TIMEOUT_S=300`; `failure_reason()`
  no-key-vs-call-failure; `analyst_layer_failed` hard-FAIL gate; traced `report_call`
  events; `silk_llm_provider.last_error()` with connect-vs-read split) and
  **deliberately refused to guess** the root cause. Evidence capture is armed and
  waiting for the next live failure. On failure the writer returns `report=None` (never
  fabricated text). Candidate fixes (wider timeout, streaming, smaller input) are
  documented as *not applied pending evidence*. This is the correct discipline — but it
  means the flagship deliverable has a live failure mode that can still recur.
- **Genericness: fixed in the hermetic harness, awaits live re-confirmation.** Root
  cause was data-starvation + flag-plumbing (8 of 12 sources never contribute for a
  keyless/flags-off user), not prose. The harness reports it closed (content-line
  divergence 82.4% ≥ 70% target); live re-confirmation via `tools/stage2c_proof.py
  --live` is still pending (`docs/GENERICNESS_AUDIT.md §6`).
- **Latent TODOs:** one honest code TODO (`silk_websearch_agent.py:59` — only `serper`
  implemented; others degrade to a *failed* report, not silent). Owner-deferred by
  settled decision (not defects): Postgres, the other 6 vision agents, trade-finance,
  CSP nonce hardening. `docs/AUDIT_STATUS.md`'s many "غير موجود" entries are a
  **pre-waves-0–5 snapshot** and mostly now implemented — do not read them as current
  gaps.

---

## 4. Economics

### 4.1 Reference rates (`silk_pricing.py:12-13,33-34`)

| Model | In $/MTok | Out $/MTok | Cache-read | Cache-write |
|---|---|---|---|---|
| `claude-opus-4-8` | 5.00 | 25.00 | 0.50 | 6.25 |
| `claude-haiku-4-5` | 1.00 | 5.00 | 0.10 | 1.25 |

Model routing is the single biggest cost driver: **Opus** runs all 12 missions,
analyst, synthesis stage-2, and the writer; **Haiku** runs the reviewer, `/ask`, and
free-path extractors.

### 4.2 Cost per operation (best estimates — labelled)

| Operation | Claude calls | Est. cost | What drives it |
|---|---|---|---|
| **Full `/research`** | ~35–40 Opus mission+analyst rounds + synthesis + 1–2 writer + 1–2 Haiku reviewer | **~$1 lean/cache-warm; up to ~$2.5–3 cache-cold + revision + greedy missions** | Opus rounds (per-mission `tool_calls` 5/9, run-wide 40-call cap), output length (missions 4000, writer 5000, analyst 6000), cache hit rate |
| **`POST /analyze`** | 4 Haiku extractors + up to 2 small Opus (stage-2 judge 900, ai_report 1800), all one reserved bundle | **~$0.05–0.15** | gated on/off by `policy["with_ai"]` + `_free_ai_extras_allowed` |
| **Report regen** | 1–2 Opus writer + 1–2 Haiku reviewer, no missions | **~$0.10–0.30** | "cents not dollars" — the cheap iteration harness |
| **Chat `/ask`** | 1 Haiku, 700 tok, 6000-char context | **~$0.005** | one call, no agents |
| **Quick snapshot** | 1 Opus tool-use (tool_calls=3, 1500 tok) + Comtrade (no Claude); cached repeats free | **~$0.05–0.15** | cost shown as `claude_activations: 1` before running |

The owner's **~$1/run is plausible** for `/research` — but only lean and cache-warm.
Prompt caching (PR #68) is what makes it so: `cache_control` on the system block and
last tool definition turns the repeated prefix from $5/MTok to $0.50/MTok across rounds
(`silk_llm_provider.py:113,158`; boundary re-marked each round
`silk_llm_runtime.py:771`). Do not "optimize" it away.

### 4.3 Metering posture (after chat/snapshot)

**Every Claude-reaching path is metered — no unmetered path found.** Each reserves ≥1
activation from `SILK_PAID_DAILY_CAP` before spending: `/deepen` (`_guard_paid`
`api.py:443`), `/analyze` extras (`api.py:498`), `/research` (`api.py:1014`), regen
(`api.py:1342`), **`/ask` (`api.py:1388`)**, **snapshot on confirm (`api.py:1469`)**.
The reservation is atomic + fail-closed (`try_reserve_paid_calls` `BEGIN IMMEDIATE`,
refuses on any DB error, never refunded, `silk_usage.py:118`).

**The nuance that matters:** the cap meters **operation count, not spend.** One
`/research` (~$1) reserves the same single unit as one `/ask` (~$0.005). So the cap
bounds *how many* expensive operations run per day, not the dollars any one consumes —
a day of `/research` at cap=50 is ~$50 worst-case, not "$50 of tokens." Comtrade has an
independent budget (`COMTRADE_DAILY_BUDGET` 450 keyed / 4 keyless; **failed attempts
count**, `silk_collectors.py:69-77`).

### 4.4 Cost risks (ranked by $ impact)

1. **Cache misses on the 40-round Opus context** (highest leverage) — a miss reverts
   the big repeated prefix to 10× ($5 vs $0.50/MTok); ephemeral cache is short-lived
   and 12 parallel missions with slow tool rounds can let the window lapse.
2. **Greedy missions maxing budget** — one deep mission at 11 Opus rounds × 4000 tok ≈
   $1.10 alone; only the run-wide 40-call cap backstops it.
3. **Revision loop firing a second writer pass** — two Opus passes × 5000 tok, each
   re-ingesting all 12 missions with no cross-call cache.
4. **Post-mission tail + resume re-spend** — analyst/synthesis/writer/reviewer are
   **not checkpointed**, so a resume correctly skips missions but **re-runs the whole
   Opus tail every time** and reserves another cap unit; a run that keeps timing out at
   the writer re-pays the tail on each retry.
5. **Model/estimate blind spot** — `SILK_AI_FAST_MODEL` is env-overridable; point it at
   Opus and every "cheap" path silently becomes Opus-priced, and an unlisted model is
   **dropped from the estimate** rather than flagged (`silk_pricing.py:52`).

**Root cause worth flagging to the owner:** risks 3–4 share one — **the
writer/reviewer/synthesis tail is governed only by `max_cycles=2`, not by the run-wide
`SILK_RESEARCH_MAX_LLM_CALLS` cap** (only `_run_loop` increments the counter, not
`_call`). The cap protects the missions, not the report-generation tail.

---

## 5. Business readiness (the owner's lens)

### 5.1 Scored against a client-readiness rubric

The referenced *10-criteria rubric* is not committed to the repo. Below is a defensible
10-criteria rubric built from committed material — the Wave-9 "sellable report" bar
(`DEEP_RESEARCH_DECISIONS.md:541`), the 8-check quality gate
(`RELEASE_NOTES_v1.md:37`), and the free/paid split (`PLATFORM_STRATEGY.md:15`) — scored
on the **best available sample output** (the *simulated* client report
`samples/client_report_latest.docx` + the `/analyze` sample `report_full_latest.md`).
Scores are this analysis's judgment; the key caveat is that no sample is from a live
run.

| # | Criterion | Score /10 | Basis |
|---|---|---|---|
| 1 | Every number sourced | **10** | Structural — `components_detail` makes an unsourced number impossible; sample shows source+date+confidence on every figure |
| 2 | Gaps declared, never filled | **10** | «فجوة معلنة» throughout; verified by the no-fabrication invariants (§3.3) |
| 3 | Professional structure/formatting | **9** | 11-section report, client/operator split, Gulf-idiom prose pass; consultancy-grade layout |
| 4 | Clear decision + thesis | **8** | verdict + confidence + conditions + 90-day roadmap present; single authoritative verdict |
| 5 | No internal plumbing leaks | **9** | defense-in-depth sanitization + raising client guard; residual = novel-token risk |
| 6 | Verified named buyers | **3** | free path unverified (0.4, ○-tagged); verified only via paid Volza |
| 7 | Verified retail prices | **3** | free path = unverified snippets; structured only via paid LocalPrice |
| 8 | Depth of analysis (5 mandates + cross-referencing) | **7** | real analytical mandate post-PR#76; capped by upstream data availability |
| 9 | Trustworthy at full strength (live-verified) | **3** | no live-verified run exists; writer-timeout can still fail; no golden baseline |
| 10 | Cost transparency to the buyer | **8** | snapshot shows cost before running; structural cost in release notes |

**Weighted read:** the *presentation and honesty* criteria (1–5, 10) score 8–10 — this
is genuinely consultancy-grade in form. The *substance and trust* criteria (6, 7, 9)
score ~3 — the differentiating data is paid-gated and nothing is live-proven. The
platform is **"ready to demo and honest," not yet "ready to invoice at premium on the
free tier alone."**

### 5.2 Sellability verdict

- **What a paying Saudi factory gets today (free `/research`):** a professionally
  formatted, fully-sourced Arabic entry study — real trade volumes and growth (Comtrade,
  when keyed), macro/demographic sizing (World Bank), country-level competitor
  concentration + HHI, a tariff/requirements checklist, a demand-trend read, a 90-day
  entry roadmap, and a clear conditional verdict — **with every gap and every unverified
  candidate honestly flagged.**
- **What it would complain about:** "the importers and the shelf prices are marked
  'unverified — verify via deepen'" — i.e. the two things a factory most wants to *act*
  on are the two things behind the paywall; and (until keys are provisioned) throttled
  Comtrade means trade figures can be thin.
- **What justifies premium pricing:** the paid `/deepen` layer (verified bills-of-lading
  buyers via Volza + structured shelf prices via SerpApi) turns the shortlist study into
  a decision study. The honest, no-fabrication posture is itself a premium
  differentiator against tools that confidently hallucinate. **The premium is real but
  currently unproven — it lives entirely in a paid path no committed run has exercised.**

### 5.3 The 3 highest-impact gaps to "a study a consultancy would sign" (ranked)

1. **No live-verified end-to-end run + no golden baseline.** *Cheapest path:* provision
   `ANTHROPIC_API_KEY` + `COMTRADE_API_KEY` + `SEARCH_API_KEY`, run **one** full
   `/research` on a well-documented market, capture it as the first real sample and the
   first `golden_cases.json` entry (pull the verifying Comtrade number directly per the
   documented runbook). This one action also arms the writer-timeout capture.
2. **Verified buyers + prices are paid-gated and unproven.** *Cheapest path:* provision
   `VOLZA_API_KEY` + `LOCALPRICE_API_KEY` and run one `/deepen` to confirm the verified
   layer produces what the report promises. (Building the free-path price normalizer,
   item 2.1, is the more expensive alternative and is deliberately deferred.)
3. **The flagship writer can still fail in production.** *Cheapest path:* the
   instrumentation is already armed — the live run in gap #1 will either reproduce it
   (then fix from captured evidence, not a guess) or clear it. Do not pre-apply a
   candidate fix.

---

## 6. Risk register

### 6.1 Top technical risks

- **The report-writer timeout (unresolved).** The one deliverable-killing bug; can
  return `report=None` on a live run. Mitigation exists (returns null not fabrication;
  hard-FAIL gate) but no root cause. *SPOF for the /research deliverable.*
- **Single LLM provider, no fallback (by design).** `AnthropicProvider` is the only
  provider; a declared stop at cap is the settled decision (`VISION.md §9.5`). An
  Anthropic outage halts all intelligence — accepted, not a defect, but a real exposure.
- **Source-outage exposure.** Comtrade keyless (~4/day) starves the core trade pillar;
  Trends/GDELT/FAOSTAT are cloud-IP/auth-blocked. Mitigations are real (mirror fallback,
  web fallbacks, circuit breakers) but several primary sources degrade to declared gaps
  under normal cloud operation.
- **The cost tail is uncapped** (§4.4) — writer/reviewer/synthesis run outside the
  run-wide call cap.

### 6.2 Top product risks

- **Data ceilings produce weak reports for whole classes of request:** keyless/throttled
  Comtrade (any market at scale); non-Latin-script markets (China/Nigeria/Egypt/Brazil)
  degrade pricing/culture web search; no free clean retail-price source exists
  (industry reality, `PLATFORM_STRATEGY.md:41`); partially-documented Arab/African/Asian
  markets carry lower-confidence "verify locally" checklists (`VISION.md:575`);
  animal-origin food-agri with unmet certification is forced to a hard regulatory gate.
- **The differentiating data is paid-gated** — the free tier, however honest, is a
  shortlist not a decision study.
- **Nothing is live-proven** — quality is asserted hermetically and on simulated
  samples only.

### 6.3 Top operational risks

- **Railway redeploys kill async runs.** `/research` is a background thread; a redeploy
  mid-run loses in-flight work. Mitigated by per-mission checkpoint + `resume=` (wave
  13) — but the post-mission tail re-spends on resume (§4.4).
- **Cost/metering:** the cap meters operation count not spend, so a modest cap can still
  permit large dollar days; the estimate under-reports unpriced models.
- **Key management:** paid keys live only in Railway env (correct), but that means the
  entire premium/verified path is untested anywhere a developer can see, and a single
  volume mounts to one service (scheduler must stay in-process — settled).
- **Governance drift:** CLAUDE.md/ARCHITECTURE.md/decisions-ledger are stale vs. PRs
  #76–#83 (§1.1) — new contributors will misread current state.

---

## 7. Verdict & roadmap

### 7.1 Updated scores

> Caveat: the external baseline (idea 9 / engineering 9 / product 7.5) is **not
> committed to the repo**; these are this analysis's fresh scores, presented against
> that remembered baseline for continuity.

- **Idea — 9/10 (hold).** A real, under-served need (Saudi non-oil export push) met by a
  tool whose core differentiator is *honesty by construction* in a category where
  confident fabrication is the norm. The reverse-discovery direction (`/discover`) adds
  genuine idea-space.
- **Engineering — 9/10 (hold).** Invariants are enforced structurally and guard-tested,
  not documented and hoped-for: one view, one verdict, structural paid boundary,
  defense-in-depth sanitization, fabrication-free data contract, 880 hermetic tests,
  stdlib-first discipline (5 deps). The one thing keeping it from 9.5 is the **complete
  absence of live-integration testing** — the whole Claude path is mocked.
- **Product execution — 7.5/10 (hold, with movement underneath).** Real breadth landed
  (client report, competing-products, snapshot, chat) with tests, and formatting is
  consultancy-grade — that pushes up. But three things hold it: the flagship `/research`
  deliverable has an **unresolved production-failure mode**, **no live-verified output
  exists**, and the **sellable data is paid-gated and unexercised**. Clear the live run
  + writer bug and this moves to 8.5.

### 7.2 The single most important next action

**Provision the paid/data keys and execute ONE fully-instrumented live `/research` run,
end-to-end, on a well-documented market — then capture it.** This one action:
(1) reproduces-or-clears the writer-timeout with the armed evidence capture (not a
guess); (2) exercises the paid verified-data path the premium price depends on;
(3) creates the missing live baseline — the first real committed sample and the first
`golden_cases.json` entry; (4) live-re-confirms the genericness fix. It is the highest
leverage available because it simultaneously retires the top technical, product, and
trust risks. Follow the credit-discipline ladder (cheap regen for any writer tweak the
run surfaces; never loop full re-runs).

### 7.3 Prioritized 90-day roadmap

| Order | Action | Type | Expected impact |
|---|---|---|---|
| 1 | One instrumented live `/research` run → capture first real sample + first golden case | Verify | Retires the no-live-baseline risk; arms writer-bug capture; unblocks everything below. **Highest.** |
| 2 | One live `/deepen` run (Volza + LocalPrice keys) → confirm verified buyers/prices | Verify/Sell | Proves the premium path; turns "sellable in principle" into "sellable, demonstrated." |
| 3 | Resolve the writer-timeout from the captured evidence (only after it recurs live) | Build | Removes the flagship's failure mode; moves product execution toward 8.5. |
| 4 | Cap the post-mission cost tail (bring writer/reviewer/synthesis under a run-level guard; checkpoint the tail so resume doesn't re-spend) | Build | Closes cost risks 3–4; makes retries safe. |
| 5 | Provision `COMTRADE_API_KEY` in prod + confirm the ~500/day ceiling lifts trade coverage from 2/30 toward full | Verify | Directly fixes the #1 data-starvation cause of weak reports. |
| 6 | Refresh governance docs (CLAUDE.md/ARCHITECTURE.md/ledger) to cover PRs #76–#83; wire the collected-but-unread WGI/LPI/FX into the risk pillar | Build/Doc | Removes governance drift + activates already-paid-for data. |
| 7 | Decide the free-path price-normalizer (item 2.1): build it fabrication-safe, or formally keep prices a paid-only feature | Sell/Decide | Settles the single biggest free-tier data gap either way. |
| 8 | Add a small live-integration smoke test (one mocked-key-real-network path in a gated CI lane) | Verify | Begins closing the largest testing gap without burning the daily budget. |

---

### Appendix — provenance of this analysis

Produced from five parallel read-only research passes over the live tree (feature
inventory + architecture; data sources + 12 missions + analyst/writer; test suite +
sanitization + invariants; cost model + metering; prior-assessment extraction), each
required to anchor claims to `file:line` or a named test, plus direct reads of the
`/analyze` sample, `ARCHITECTURE.md`, the decisions ledger tail, CI config, and
`requirements.txt`. No live or paid calls were made. Where the commissioning brief's
baselines (10-criteria rubric, 9/9/7.5 scores, 3/7/2 scorecard, Phase-3 sellability
note) were sought in `docs/` and not found, that absence is stated explicitly rather
than papered over — consistent with the repo's own AUDIT_STATUS method.

# FULL PLATFORM AUDIT — 2026-07-20

> **Read-only forensic audit.** Nothing was fixed. This is a prioritized defect
> inventory, the input to a future fix cycle. Every row is anchored to `file:line`
> with quoted evidence; "not found / clean" is stated explicitly where checked.
>
> Evidence classes used: **direct reproduction** (ran it), **static code review
> (file:line)**, **no sufficient evidence — pending** (needs a live check the
> sandbox can't do → marked OWNER-VERIFY).

## Method & coverage

- Read `docs/LESSONS.md` (rows #1–#31), `docs/DECISIONS.md`, `docs/SPEC-v2.md` in
  full; built a per-incident hunt checklist and re-hunted every family across the
  whole tree (not just its original fix site).
- Partitioned the repo into 10 modules and dispatched one deep read-only reviewer
  per partition (api / engine / storage / llm-writer / data-agents / reports /
  render / frontend / tests / tools-docs). Every partition read its files in full.
- The two highest-severity code claims were re-verified by hand (see §"Independent
  verifications").

**Coverage denominator (code files, excluding vendored fonts/generated samples):
229** = 220 `.py` (57 root modules + 144 `tests/` + 19 `tools/`) + 3 `.html`
+ 3 `tests/e2e/*.cjs` + 3 `migrations/*.sql`. Plus config/data reviewed
separately (Dockerfile, 3 workflows, railway.json, netlify.toml, `.env.example`,
`config/branding.yaml`, `requirements.txt`, 12 `data/*.csv`, governance docs).

**Coverage ratio: 229 / 229 = 100%.** All 57 root modules + `api.py` were reviewed
line-by-line; `silk_reports.py` (3474L) and `silk_render.py` (1540L) fully; the
frontend fully. `tests/` (144 files) were reviewed at **coverage-map depth**
(module→test mapping, regression-registry integrity, weak/non-hermetic-test
detection) rather than bug-hunting each assertion — appropriate for a test suite.
`tools/` (19) and workflows read in full; governance docs cross-checked.

**Baseline health (direct reproduction):** `python3 -m pytest tests/ -q` →
**1306 passed, 17 skipped, 1 warning in 167s**. This is **rung-1 hermetic only**.
Per LAW §2 / LESSONS #15 that is **not "ready for owner"** — rungs 2 (real uvicorn)
and 3 (Playwright) were **not** run in this sandbox (no server/browser + no live
deploy URL committed). All live-surface items below are OWNER-VERIFY.

---

## Cross-cutting sweeps (Phase 3)

**Sweep #1 — every disk/DB write routes through the DATA_DIR-aware helper.**
CLEAN. All five stores — analyses `silk.db`, fact store `silk_store.db`,
`usage.db`, request `cache/`, **and a 5th store not named in the "four stores"
rule: `ops_errors.db`** — resolve their path via `path or _db_path()` →
`SILK_*` → `SILK_DATA_DIR` → literal fallback. The `_DEFAULT_PATH="data/…"`
literals (`silk_storage.py:17`, `silk_store.py:25`) are reachable only when both
the per-store var and `SILK_DATA_DIR` are unset (documented open-dev mode). No
production caller passes a relative literal. The #31 `/analyze` bug is fixed and
stays fixed (`silk_engine.analyze(db_path=None)` at `silk_engine.py:55`).
→ Observability nit only: `ops_errors.db` is absent from the `/health` storage
inventory (see M-16).

**Sweep #2 — every model id ↔ pricing-table entry.** CLEAN for defaults. All
routed defaults are priced: `claude-opus-4-8` exact (`silk_pricing.py:12`),
`claude-haiku-4-5-20251001` via the `claude-haiku-4-5` prefix (`:13`, longest-prefix
sort at `:18-19` prevents collision). Residual risk = operator override
(`SILK_AI_MODEL`/`SILK_AI_FAST_MODEL`/`SILK_MISSION_MODEL`/`SILK_INTAKE_MODEL`) to
an unpriced id → understated cost, but **declared** via `unpriced_models` +
`complete=False` (honest, not fabricated). See M-19.

**Sweep #3 — every external API call degrades to a declared gap AND is recorded.**
Declared-gap: **CLEAN everywhere** (no fabrication on failure found in any agent).
Ops-visibility (#26 `record_service_failure`): **INCONSISTENT** — the two most
important sources (Comtrade, World Bank) and WITS + web-search record **nothing**;
FAOSTAT-auth / Maps-non-OK / GDELT-429 record only their generic branch. This is
H-3, the single most systemic finding.

**Sweep #4 — user-facing string sweep (`§`, deleted-feature refs, stray English).**
Served `web/index.html`: **CLEAN** — no `§` in rendered text (only two JS
comments), no `snapBtn`/`معاينة فورية`/`لقطة سريعة`/`products/snapshot`, runbar has
exactly the two required buttons. Two exceptions: an undefined i18n key surfaces the
literal `readFailMsg` (M-24), and the orphan `docs/mockups` + `docs/redesign` HTML
still contain the deleted `حلّل السوق` label (M-23). `§8` **does** reach
*operator*/report faces from the render + reports layer (M-9, L-2) — not the client
PDF.

**Sweep #5 — reproduce every DECISIONS "DONE-with-artifact" claim now.**
**ALL REPRODUCE.** A1,A2,A3,B1,B2,B3,C2,C3,C4,C5,D1,D2,D3,E1,E3 each verified by
its cited guard/test/absence-grep in the current tree (test counts match or exceed
the ledger). "google_maps configured-but-unused" and "ai_verdict deleted" still
hold. **E2/#6 cost target is still honestly "NOT DONE"** in code: `_WRITER_MAX_TOKENS=16000`,
`_MAX_TOKENS_CEILING=32000`, `_ANALYST_MAX_TOKENS=12000` match the documented refix;
no in-repo live cost reconciliation exists. The only defect: `docs/DECISIONS.md:153`
open-question line-number citations have drifted (L-14).

---

## Independent verifications (re-checked by hand, not just reported)

- **C-1 / H-1 (consumer gate):** CONFIRMED. `silk_engine.py:244` calls
  `_consumer_culture(...)` (paid Claude) **before** the `_agent_on("consumer")`
  disable check at `:250-252`; `with_websearch = False` at `:252` is a dead
  assignment (no later read).
- **H-3 (Comtrade ops-log):** CONFIRMED. `silk_data_layer.py` has **zero**
  references to `ops_log`/`record_service_failure`; the Comtrade `except`
  (`:354`) and World Bank `except` (`:483`) are `log.warning(...)` + `return None`
  only.
- **H-2 (vendor leak):** CONFIRMED across three layers — `silk_quality_gate.py`
  has no vendor patterns (grep = 0); `silk_reports.py:1612-1618` has them only in
  the **client-export** sanitizer; `silk_render.py:216` stamps raw `Volza`/`explee`
  into the view; `web/index.html:964` renders that source raw. So the dashboard +
  operator-md leak; the client **PDF/docx are protected**.

---

## MASTER DEFECT TABLE (Critical → High → Medium → Low)

Category legend: correctness / security / perf / consistency / dead-code / test-gap
/ fabrication (no-fabrication-contract breach) / confidentiality (client-leak).

| # | file:line | finding | category | evidence | suggested direction |
|---|---|---|---|---|---|
| **C-1** | `silk_render.py:905-910` (+949-978) | **No-fabrication breach on the client limits line.** The «أسعار» reconciliation topic uses `need_kw_in_fact=False` with an `evidence_re` matching any bare currency figure (incl. `$`/`دولار`). Any USD number in an *unrelated* trade-value finding retags a genuinely-unmet price gap as «حُسمت لاحقاً» in the client report — the exact #12 family the reconciler was built to prevent, now re-opened. High trigger likelihood (most reports carry a USD figure). | fabrication | `evidence_re: r"…(?:€\|\$\|£\|ريال\|يورو\|دولار…)…"` with `"need_kw_in_fact": False`; resolver stamps `f"حُسمت لاحقاً …: {line}"` | Require a per-unit/retail signal (`/كجم`) or set `need_kw_in_fact=True` for the price topic; add a negative lock test (a USD trade-value fact must NOT resolve a price gap). |
| **H-1** | `silk_engine.py:239-252` | Consumer-culture **paid Claude call fires before** the panel disable check. Disabling the "consumer" agent row neither prevents the Serper+Claude spend (`_consumer_culture` at :244) nor removes `result["consumer_culture"]`; `with_websearch=False` at :252 is dead. Contrast the correct dynamics gate at :247 (before its block). | correctness / money-path / operator-intent | `if with_websearch: … result["consumer_culture"]=_consumer_culture(…)` **then** `if with_websearch and not _agent_on("consumer"): … with_websearch=False` | Move both `_agent_on` checks above the websearch block (mirror dynamics); add a hermetic test that a disabled "consumer" row yields no `consumer_culture` and zero Claude calls. |
| **H-2** | `silk_render.py:216`; `web/index.html:964`; `silk_quality_gate.py:157-166`; `silk_missions.py:261-266` | **Vendor-name leak to the dashboard/operator surface (#18).** `_suppliers` stamps raw `"Volza"/"explee"` into the canonical view; the dashboard renders `esc(sx.source)` raw; the deterministic confidentiality gate has **no** vendor patterns; and the risk_news mission *instructs the model to name "GDELT"* in a declared gap. Only the client PDF/docx sanitizer (`silk_reports.py:1617`) catches these — every other consumer of the view leaks. | confidentiality / consistency | `("volza","Volza"),("explee","explee")`; gate patterns end at `⚠` with no vendor entry; mission: `"أعلن فجوة تسمّي المصدر … (GDELT 429/شبكة…)"` | Emit a generic source label in `_suppliers` (raw only behind `?internal=1`); add vendor patterns to `silk_quality_gate`; have risk_news declare the gap generically («مصدر الأخبار»). |
| **H-3** | `silk_data_layer.py:353-356, 483-486` (+WITS `silk_tariffs_agent.py:118`, websearch `silk_websearch_agent.py:88,167`, FAOSTAT-auth `silk_faostat_agent.py:108`, GDELT-429 `silk_gdelt_agent.py:70`, Maps-nonOK `silk_maps_agent.py:66`) | **#26 silent-external-failure, systemic.** Comtrade & World Bank fetch failures (incl. the real 429 incident) degrade to `None` but only `log.warning` — never `record_service_failure`, so they are invisible in `/ops/last-errors` (Railway logs are proxy-blocked). `silk_data_layer.py` imports `ops_log` **nowhere**. The registry guard `_guard_silent_external_failure` only asserts the scraper, so this slips through despite #26 naming Comtrade as the exemplar. | correctness / observability | `log.warning("Comtrade fetch failed …"); return None` (no ops row); grep `ops_log` in silk_data_layer = 0 | Record `record_service_failure("comtrade"/"worldbank"/…)` in each `except` (side-channel try); extend the registry guard to assert Comtrade+WB+WITS+websearch. |
| **H-4** | `api.py:2039-2042, 2064-2067, 2116-2119, 2154-2157` | `brief` / `report.docx` / `report.pdf` / `report.md` call `build_view(found)` **outside** any try/except, unlike every other site which uses the safe `_view()` wrapper (`api.py:311-318`). A malformed stored blob → `build_view` raises → **500 crash** on export/reopen instead of a declared-gap/clean error. | correctness | `view = build_view(found)` with no guard vs `_view()` wrapper elsewhere | Route all four exports through `_view()` (or a shared guarded helper). |
| **H-5** | `api.py:1900-1902` | `/diagnostics` **top-level** `except` returns the raw exception string, bypassing `silk_diagnostics._redact`. Per-probe errors are redacted, but if `run_diagnostics` itself raises, `{e}` can carry a URL/header holding a live key straight to the client. | security | `return {… "error": f"{type(e).__name__}: {e}" …}` | Run the message through `_redact` before returning. |
| **H-6** | `silk_market_analyst.py:231-236`; `silk_llm_runtime.py:991-1014` | Analyst has **no max_tokens escalation ladder** (unlike the writer). On truncation the JSON fails to parse, one repair fires at the **same** `max_tokens`, re-truncates, and the analyst returns empty → all 5 intersections «دليل غير كافٍ». `_ANALYST_MAX_TOKENS=12000` was sized before the instructions grew (triangulation+benchmark+so-what+decision-impact+critical-gap) — the #16 pattern, one layer down from the fixed writer. | correctness / #16 | repair: `_call_tools(…, max_tokens=max_tokens …)` — same budget as the truncated call | Give the analyst the writer's escalate-to-ceiling loop, or size the repair at `_MAX_TOKENS_CEILING`. |
| **H-7** | `silk_evals.py:213` (+75-79) | Eval judge prompt reports **every mission as `failed=False`**: `_report_fields` returns only `{"findings":…}`, so `.get('failed', False)` is unconditionally False. The Claude judge is told all 12 missions succeeded, corrupting the `gaps_declared` / `section_completeness` scores. | correctness (wrong field) | `f"…فشل={_report_fields(v).get('failed', False)}"` while `_report_fields` returns `{"findings": …}` | Have `_report_fields` also return `failed`, or read `v.get("failed")` directly. |
| **H-8** | `silk_seed_data.py` (module) | **Zero tests.** The bundled World-Bank seed path (`data/worldbank_seed.csv`) has no hermetic "None-on-missing-country, not fabricated" assertion — a customer-visible data path outside the founding-principle test discipline. | test-gap / fabrication-risk | `grep seed_data tests/` = 0; module docstring promises `None` on absence, nothing asserts it | Add a hermetic test: known country → real tagged value; absent/synthetic ISO → `None` (not 0), with source+year. |
| **H-9** | `.github/workflows/e2e-live-shape.yml` | The rung-2/3 gate (real server + Playwright, LESSONS #15/#19) is a separate workflow whose "**required status check**" is a manual GitHub branch-protection setting — **not enforceable or verifiable in-repo**. A PR touching `web/index.html` or an export path can merge with e2e red if the owner hasn't set the protection. (Job itself has no `continue-on-error` — good.) | consistency / CI | header: "حماية الفرع (يضبطها المالك في GitHub)… اجعل الفحص مطلوباً" | Commit the exact required-checks list; add a meta-test asserting the workflow + job name exist; document a periodic branch-protection check. |
| **M-1** | `silk_market_ranker.py:537-558` | Budget-exhaustion self-contradiction: logs "degrading to Tier-1 curated only (no Tier-2 fabrication)" and skips the world call, then the `SILK_DYNAMIC_MARKETS` path (default on) immediately calls `top_import_markets`→`world_import_totals`→the **same** `comtrade_trade(partner=0)` world call it just declined on budget grounds. | correctness / budget | `log.info("… budget exhausted … Tier-1 only")` then `if …SILK_DYNAMIC_MARKETS!="0": dyn = top_import_markets(...)` | Have the dynamic-candidates path honor `_comtrade_budget_left()`; on exhaustion fall to curated `COUNTRIES` with no further world call. |
| **M-2** | `silk_market_ranker.py:25,93,348,470`; `silk_research.py:495-502`; `silk_discovery.py:31` | Origin **hardcoded to Saudi** (`_SAUDI_M49="682"` / `partner="SAU"`) across ranker/research/discovery, while `silk_prerun.origin_iso3()` reads `SILK_ORIGIN_ISO3`. With a different origin the "skip origin as a target" logic breaks (wrong-direction-study family) and `saudi_position`/`saudi_gap` never re-target. Config defined in 2 places → drift. | consistency / wrong-direction | `_SAUDI_M49 = "682"`; `if not m49 or m49 == _SAUDI_M49:` | Route origin through one config source (`origin_iso3()`→M49) shared by all three; keep "Saudi" only as a display label; add a lock test. |
| **M-3** | `api.py:1262-1263` vs `silk_usage.py:226-250` | USD reconcile keyed on `_today()`, not the reservation's day. A `/research` run that reserves before UTC-midnight and reconciles after applies the delta to the wrong daily bucket: reserve-day over-counts forever, reconcile-day floors at 0. The reaper guards this; the normal completion path does not. | correctness / cap | reconcile: `"… WHERE day = ?", (_today(),)` | Pass the reservation's day into `reconcile_usd`. |
| **M-4** | `silk_ai_judge.py:1034-1072` | `deep_report` ships a **truncated partial** when an escalation retry fails with a *non-truncation* error. `truncated` is set True only at the ceiling (:1053); if attempt-0 truncates and attempt-1 returns None (network), the loop breaks with `truncated=False`, so the `_writer_incomplete` §5 guard (`if best and truncated`, :1064) never runs and a mid-sentence draft ships. | correctness / #16 | `truncated = True # بلغ السقف الصلب` only at ceiling; guard `if best and truncated:` | Track "best came from a max_tokens call" independent of the ceiling; run the incompleteness guard whenever so. |
| **M-5** | `silk_market_analyst.py:231-232` | Budget footgun: `eff_budget.setdefault("max_output_tokens", _ANALYST_MAX_TOKENS)`. A caller passing a mission-sized budget (`max_output_tokens: 4000`) silently caps the analyst at 4000; the 12000 floor only applies when the key is absent. | correctness / #16 | `eff_budget.setdefault("max_output_tokens", _ANALYST_MAX_TOKENS)` | `eff_budget["max_output_tokens"] = max(passed, _ANALYST_MAX_TOKENS)`. |
| **M-6** | `silk_reports.py:1790-1809` | Client guard joins paragraphs with `\n` and multi-token forbidden patterns use `\s+` (matches newline), so a forbidden phrase split across two paragraphs trips `_client_assert_clean` — but `_client_redact_residual` redacts **per-paragraph** and cannot neutralize a cross-paragraph match. The exact repeat-501 (#11) family: guard scope ≠ redact scope. | confidentiality / #11 | guard `blob = "\n".join(parts)`; patterns e.g. `فجوة\s+معلنة` | Redact on the same joined blob the guard inspects (or forbid `\s` spanning `\n`). |
| **M-7** | `silk_reports.py:1804-1808` vs `:562-566` | Client confidentiality redactor/guard scan only `doc.paragraphs` + `doc.tables` — **not** `section.header`/`footer`. `_add_page_header_footer` writes `view["product"]` into every page header; a forbidden/vendor term in the product name ships into the client header/footer uncaught (#18 blind spot). | confidentiality / #18 | guard collects `[p.text for p in doc.paragraphs]` + cells only | Extend redact+assert to walk `section.header/footer.paragraphs` (as `_finalize_rtl` already does at 487-489). |
| **M-8** | `silk_reports.py:1474` vs `3060`; `1475` vs `1562,1578` | Deep-research **limits & heading drift between docx and md siblings**: Word reads `dr["limits"]` (subset) via `_clean_report_text(…,600)` (may append «…»); Markdown reads `view["limits"]` (superset) via `_gap_list_ar`. Word TOC/exec-summary promise «حدود هذا التقرير» but the body heading is «حدود قسم البحث العميق», and the section is omitted when `dr["limits"]` is empty while the TOC still lists it. | consistency / contradiction / #12 | docx `dr["limits"][:12]` vs md `view["limits"]`; heading `"حدود قسم البحث العميق"` vs TOC `"حدود هذا التقرير"` | Both deep exporters read `view["limits"]` via one helper; make heading == promised label; always emit the section. |
| **M-9** | `silk_reports.py:876,878,3419` (rendered 1053,3133) | Internal plumbing «المحرك الموزون (§8)» / «(§8)» reaches the **rendered report face** via the entry-decision *absent* strings and the markdown risk fallback — contradicting the leak-fix at 1045-1049. docx risk line (1090) has no §8; markdown (3419) does → sibling drift too. | confidentiality / consistency | `"قرار الدخول غير متاح — المحرك الموزون (§8) لم يعمل"`; `"- لا مخاطر… (§8)"` | Scrub these absent/fallback strings; align md risk line to the §-free docx wording. |
| **M-10** | `silk_reports.py:2420-2425` | PDF conversion failure surfaces only the generic `_PDF_FAILED`; `proc.stderr/stdout` from soffice are discarded on both the exception and the returncode branches → dlReport gets a bare status, not the real cause (#11). | correctness / #11 | `except Exception as e: raise RuntimeError(_PDF_FAILED) from e` | Include a redacted tail of `proc.stderr` in the error so the 501 body carries the cause. |
| **M-11** | `silk_render.py:340-360` (rendered `web/index.html:845,928`) | Evidence-log `source` field is **not** passed through `_map_mission_keys`/`_strip_internal_plumbing` (only the failure *note* is, :358). A finding whose `source` is a mission name or «(Claude tool-use)» leaks into the evidence log (#14 covers prose, not this field). | confidentiality / #14 | `src = str(d.get("source") or "?")`; only `failure = _strip_internal_plumbing(str(d.get("note")))` | Pass `source` through `_map_mission_keys`/an allow-list before grouping. |
| **M-12** | `silk_render.py:1235-1237` vs `:1190` | **Verdict-precedence mismatch.** `next_step` reads `verdict.get("verdict") or ai.verdict` (top-level first) while `verdict_tone`, `_decision`, `_deep_research_brief` use AI-first. If jury and AI verdicts differ, the paid-deepen upsell and the badge tone disagree on the same report. | consistency / correctness | `str(verdict.get("verdict") or (verdict.get("ai") or {}).get("verdict") …)` vs `v_raw = (verdict.get("ai") or {}).get("verdict") or verdict.get("verdict")` | Use AI-first precedence in `next_step`. |
| **M-13** | `silk_render.py:1113` vs `silk_market_analyst.py:41-50` | Literal-5 intersection list **duplicated**: `_cat_tag_re` hardcodes `(?:demand\|price_competitiveness\|entry_cost\|entry_door\|swot)`, which must stay identical to `_CATEGORY_LABELS` keys (also used by `silk_quality_gate`). No test binds them; renaming a category silently breaks tag-stripping. | consistency | `_cat_tag_re = re.compile(r"^\[(?:demand\|…\|swot)\]\s*")` | Build the regex from `_CATEGORY_LABELS.keys()`, or add a set-equality test. |
| **M-14** | `silk_discovery.py:190-196` | Four independent Comtrade calls (`newer`/`older`/`saudi_in`/`saudi_x`) run **sequentially** though the ranker already uses a ThreadPoolExecutor for the same pattern — ~4× wall-clock on `/discover`. | perf | four blocking `_totals_by_hs(comtrade_trade(...))` in a row | Gather the four in a `ThreadPoolExecutor(max_workers=4)`. |
| **M-15** | `api.py:228-256` vs `818-857` | `AnalyzeRequest` declares `with_trends/with_tariffs/with_faostat/with_maps/with_websearch/with_competitors/with_channels/with_importers/with_requirements/with_trend`, but `/analyze` ignores them all and uses `**_source_policy()`. Clients are misled into thinking these flags control sources. | dead-code / consistency | `result = silk_engine.analyze(… **policy)` — no `req.with_*` read | Drop the unused booleans (or document them as no-ops). |
| **M-16** | `api.py:1865` | `/trend` hardcodes `end_year = req.end_year or 2023`; in 2026 the trend tab silently queries a 3-year-stale end year, unlike `_readiness_checks`/`_market_in_coverage` which use `date.today().year-1`. | correctness / consistency | `end_year = req.end_year or 2023` | Default to `date.today().year - 1`. |
| **M-17** | `api.py:2063-2139` | `report.docx`/`report.pdf` create `tempfile.mkdtemp()` per request and never clean it up; on Railway's fixed disk allowance these accumulate on every export. | perf / disk | `render_docx(view, os.path.join(tempfile.mkdtemp(), …))` with no cleanup | Clean the dir via a `BackgroundTask` after send. |
| **M-18** | `silk_gmaps.py:313-337` | `places_fallback` calls `silk_maps_agent.find_places` **directly**, outside BaseAgent/panel gating. Disabling the "maps" agent row still hits the billable Google Places API on the scraper fallback. | consistency / money-path | `from silk_maps_agent import find_places … for dp in find_places(...)` | Check `agent_enabled("maps")` before the Places fallback, or route through `MapsAgent`. |
| **M-19** | `silk_pricing.py:11-28` + env overrides | A `SILK_*_MODEL` override to a non-Opus/Haiku id is unpriced → understated cost, and `reconcile_usd` then swaps the flat reservation for the understated actual, under-enforcing the daily USD cap the rest of the day (#16 family). Honest (declared `complete=False`), but the money-gate degrades silently. | pricing / cap | table holds only opus/haiku prefixes; overridable via 4 env vars | On `complete=False`, log a loud ops row and/or use a conservative fallback rate for **cap** purposes (not the reported figure). |
| **M-20** | `silk_research.py:926,1168-1170,1208` vs `silk_data_layer.py:417-420` | `LP.LPI.*` (LPI) and `IC.IMP.TMBC` (border-compliance) are queried via `world_bank()` but **not pinned** in `_WB_INDICATOR_SOURCE` (which covers only WGI). Same class as the #7 WGI-source-3 incident: if WB migrates them they degrade to a silent declared gap. Evidence: static — needs a live WB probe. | correctness / #7 (latent) | `_WB_INDICATOR_SOURCE = {"PV.EST":"3", …}`; `world_bank(iso3,"LP.LPI.OVRL.XQ")` unpinned | OWNER-VERIFY: live-probe LPI/IC.IMP.TMBC; if empty from the default source add their `source` id. |
| **M-21** | `silk_eurostat_agent.py:57,62` (docstring 16-20) | Eurostat dataset codes `hbs_str_t223`/`migr_pop3ctb` are **self-declared unverified** ("بلا اتصال شبكة للتحقق"). A wrong code → HTTP 400 → declared gap (no fabrication) but the mission silently yields nothing (#7 family). | correctness / #7 (latent) | `_HBS_DATASET = "hbs_str_t223"` + docstring admission | OWNER-VERIFY: run the 2-3 live probes the module itself requests; pin verified codes. |
| **M-22** | `api.py:1038-1039,1157,1262,1675,2293` | Several env numeric parses lack the `or "<default>"` fallback used at :628-629. `int(os.environ.get("SILK_RESEARCH_MAX_LLM_CALLS","40"))` raises on a set-but-empty var, 500-ing the research build (wasted paid run) on operator misconfig. | correctness | `int(os.environ.get("SILK_RESEARCH_MAX_LLM_CALLS","40"))` (no `or "40"`) | Add a small `_int_env/_float_env` helper tolerant of empty strings. |
| **M-23** | `docs/mockups/silk_prototype.html`; `docs/redesign/enterprise-preview.html` | Orphan/dead artifacts — served by no route (only `web/` is mounted, `api.py:2390`). The mockup still contains the **A2-deleted** live label «حلّل السوق» and hardcoded placeholder data; both load Google-Fonts CDN (violates the self-hosted-fonts rule if ever promoted). `web/index.html:10` still calls the mockup «النموذج الملزم» though the UI has diverged. | dead-code / consistency | `<button class="runbtn" …>حلّل السوق…`; CDN `fonts.googleapis.com` | Archive/delete or add a "non-adopted concept" header; fix the stale pointer comment. |
| **M-24** | `web/index.html:442` | `t("readFailMsg")` — key not defined in `T`, so `t()` returns the truthy literal `"readFailMsg"`, the `\|\|` Arabic fallback never fires, and the raw identifier is shown to the user on an oversized-image intake (behind `SILK_IMAGE_INTAKE`, so latent). | correctness / stray-string | `intakeCardMsg(t("readFailMsg")\|\|"حجم الصورة يتجاوز ٥…")` | Add `readFailMsg` to `T` or use the Arabic literal directly. |
| **M-25** | `silk_market_ranker.py:512`; `silk_discovery.py:32` | Stale hardcoded default-year literals: `rank_markets(… year=2022)` and `_DEFAULT_YEAR=2022`. Engine always passes a real year, but any direct caller (`/discover` without a year) studies 2022 data in 2026. | correctness / stale-literal | `def rank_markets(…, year: int = 2022, …)`; `_DEFAULT_YEAR = 2022` | Default to `date.today().year - 1`. |
| **L-1** | `silk_render.py:72,105` (+1430-1433) | Latent KeyError: `max(feas, key=lambda f: f.get("margin_at_match_pct", -9e9), default=None)` can return a thread lacking that key; `_brief` then hard-subscripts `best['margin_at_match_pct']`, crashing view construction. Same hard-subscript in `render_text`. | correctness (latent crash) | `f"…{best['margin_at_match_pct']}%" if best else …` | Use `.get(...)` with a declared-gap fallback. |
| **L-2** | `silk_render.py:1264` | Orphan «§8» in a surfaced view field: `decision.stage = "silk.decision/v1 — المحرك الموزون §8 (الحكم الوحيد)"` reaches the dashboard. | dead-code / orphan-§ | `"stage": "silk.decision/v1 — … §8 …"` | Drop the «§8» token from the surfaced string. |
| **L-3** | `silk_render.py:131,135` | `_deep_research_brief` guards on non-empty list but not `value is None`; `demand[0].get('value')` can render «الطلب الفعلي المقدَّر: None» into the mobile brief. | correctness (placeholder) | `lines.append(f"…: {demand[0].get('value')}")` | Skip the line when value is None. |
| **L-4** | `silk_ai_judge.py:164-173` | On the single-turn `_call` path an empty max_tokens truncation meters cost but skips `count_data("llm_calls")` (guarded by `if out is not None`). Dollar cost stays correct; the call **count** under-reports. | metering / #16 | `if out is not None: … count_data("llm_calls")` | Count the llm_call whenever the HTTP request completed. |
| **L-5** | `silk_llm_runtime.py:844` | `[TOOLS[k]["spec"] for k in allowed if k in TOOLS] or None` silently drops any mission tool absent from the registry (all resolve today; a future typo is invisible). | consistency | `for k in allowed if k in TOOLS` | Log a warning on `k not in TOOLS`; add a registry-parity test. |
| **L-6** | `silk_market_resolver.py:44-46` | `_load` swallows all exceptions and returns `[]` with **no log**; a corrupt `countries.csv` makes every `resolve_market` silently return `(None, [])`, unlike the HS resolver which logs. | empty-except | `except Exception: return []` (no log) | Add `log.warning(...)` to match `load_hs_codes`. |
| **L-7** | `web/index.html:921,923` | Classic-board verdict tag + confidence are parsed by string-splitting/regex over the human `brief[0]` (`split("—")`, `match(/ثقة ([^)]*)\(/)`); if `silk_render` phrasing changes, the tag silently falls back with no error. | correctness / consistency | `esc(brief.split("—")[0].replace("التوصية:","")…)` | Prefer structured `decision.tone`/confidence fields over re-parsing prose. |
| **L-8** | `web/index.html:346` | `document.getElementById("adminKey")` — no such element (the key is a `window.prompt`); guarded by `if(ak)` so harmless, but a dead reference. | dead-code | `var ak=document.getElementById("adminKey");if(ak)…` | Remove the dead lookup. |
| **L-9** | `silk_websearch_agent.py:58-63` | `SEARCH_PROVIDER` TODO — only `serper` implemented; others degrade to a **declared failed DataPoint** (verified correct, not a crash/fake). Informational: the only real TODO left in production code. | dead-code (informational) | `# TODO: implement other providers …` | No action; note it degrades correctly. |
| **L-10** | `silk_faostat_agent.py:164-170` | `FaostatAgent` sets no `PREF_KEY`/`SOURCE` and FAOSTAT has no `AGENT_CATALOG` row, so it can never be toggled from «إعدادات الوكلاء», unlike its peers. | consistency | `class FaostatAgent(BaseAgent): PAID = False` (no PREF_KEY) | Add a catalog row + PREF_KEY, or document it as intentionally internal. |
| **L-11** | `silk_research.py:1309-1353` vs `silk_decision.py:34-39` | The 8th agent's `pillar_inputs["logistics"]` (lead time, freight, landed cost, LPI) is computed but `decide()` has no logistics pillar in `WEIGHT_OPTIONS` and never reads it — dead relative to the score. | correctness / unreachable-data | `"logistics": {…}` built; `WEIGHT_OPTIONS` keys are market/competition/regulatory/profit/risk only | Surface logistics in the report explicitly, or fold a signal into risk/profit. |
| **L-12** | `silk_reports.py:92` (via 105,147-163) | Two truncation policies coexist: `_truncate_at_word` appends «…»; `_trim_sentence` was written to avoid it («بلا نقاط حذف»). Trailing mid-sentence «…» still reaches report faces (#14/#16). | correctness / #14 | `return cut.rstrip() + "…"` | Standardize customer-facing truncation on `_trim_sentence`. |
| **L-13** | `tools/acceptance_run.py:253` | Dead variable: `unpriced = econ.get("cost_usd_by_model") and …` assigned but never read (the summary reads the value directly at :258). | dead-code | `:253` vs `:258` | Delete line 253. |
| **L-14** | `docs/DECISIONS.md:153` | Open-question line citations drifted: `/health` google_maps cited `api.py:315-317`, now `:356-358`; runtime registry `silk_llm_runtime.py:143-406`. Content reproduces; anchors stale (violates the file:line discipline). | doc-accuracy | grep shows google_maps health at `api.py:356` | Refresh the cited ranges or use symbol-based citations. |
| **L-15** | `Dockerfile:18-21`; `.github/workflows/e2e-live-shape.yml:42-45` | Build/CI fetch fonts via `curl -fsSL` from `raw.githubusercontent.com/google/fonts/**main**` (unpinned branch). `-f` + a later `fc-list` check fail loudly (no silent substitution), but availability/repro depends on GitHub `main`. | deploy / supply-chain | `curl -fsSL … /main/ofl/ibmplexsansarabic/…` | Pin a commit SHA or vendor the OFL TTFs. |
| **L-16** | `api.py:375-404`; `silk_ops_log.py` | `ops_errors.db` (5th persistent store) is absent from the `/health` storage inventory and the boot-trap/warning enumeration (four stores only). Routes via `SILK_DATA_DIR` correctly, so no data-loss — observability gap only. | observability | health `storage` dict lists 4 keys | Add `ops_log_db: silk_ops_log._db_path()` to `/health`. |
| **L-17** | `tests/test_regression_registry.py:135,167` | Two trap guards (`_guard_trap_redaction_mangling`, `_guard_trap_parallel_cache_window`) are **existence-only** (symbol presence), not behavioral — cannot fail on a real regression. Openly labeled as known-unfixed traps, so acceptable, but not real guards. | weak-test | comment: «بنيوياً مفتوح — لا حارس … بعد» | Upgrade to behavioral assertions when each underlying trap is closed. |
| **L-18** | `silk_render.py:1039`; `silk_gdelt_agent.py:31`; `silk_diagnostics.py:178` | Minor: redundant local `import re` inside `_apply_merchant_language` (already module-level); a personal GitHub URL literal in the GDELT User-Agent; a repeated default model-id literal `"claude-opus-4-8"` in the diagnostics probe (env-overridable). | dead-code / hardcode (minor) | `def _apply_merchant_language(…): … import re` | Remove the local import; centralize the default model-id literal. |
| **L-19** | `api.py:325-416` | `/health` (intentionally unauthenticated) leaks absolute filesystem paths and the **names** of configured paid-provider keys to anonymous callers. | security (low) | `health["storage"] = {"analyses_db": _db_path(), …}` + `_unprotected_paid_keys()` | Gate the `storage` paths + key-name warnings behind `_require_key`, or reduce to booleans. |
| **L-20** | `silk_requirements_agent.py:203-224` | When a market is uncovered by L1 and has no exit items, `_execute` returns `failed=False` with a single `DataPoint(None)` — a "successful" report carrying only a gap (mildly misleading; the jury's `_real` filter handles it). | correctness (minor) | `findings.append(DataPoint(None, …)); return AgentReport(…, False, …)` | Set `failed=True` when no value-bearing item exists. |
| **L-21** | `silk_style_contract.py` (module) | Zero direct tests on the style/glossary/currency contract constants (effect tested in render). A silent edit re-enabling SAR conversion the §1 note forbids would fail no test. | test-gap | `grep style_contract tests/` = 0 | Add a contract-level lock: currency-stays-USD + glossary-present. |

---

## Convergent / systemic themes (for the fix cycle)

1. **Guard-layer inconsistency is the dominant pattern.** The two founding
   contracts each have **multiple guard layers that disagree on scope**:
   confidentiality (H-2, M-6, M-7, M-9, M-11 — client PDF is protected, but the
   view/dashboard/operator-md/headers/evidence-log/absent-strings each leak through
   a different hole); and ops-visibility (H-3 — declared-gap is universal but
   `record_service_failure` is not). Fix direction: make each contract's guard a
   single choke-point that every consumer passes through, not per-exporter patches.
2. **#16 token-budget family recurs one layer below the fixed writer** (H-6, M-4,
   M-5, L-4) — the analyst and the writer's retry/metering edges were never
   re-measured after the writer fix.
3. **Origin/year/category are still single-cased or duplicated** (M-2, M-13, M-16,
   M-25) despite the "config-driven, no hardcoded rule" lessons (#24/#25).
4. **`/analyze` (pipeline 1) remains the less-hardened sibling** (H-1, M-15, M-16)
   — the exact "a second pipeline never got the attention" pattern behind #31.

## OWNER-VERIFY (live checks the sandbox can't do)

No live deploy URL is committed (good practice), so these need the owner's host:

- Rungs 2 & 3 (real server + Playwright) — `SILK_RUN_E2E=1 pytest tests/test_rung2_real_server.py tests/test_rung3_playwright_e2e.py`.
- Live `/health`, a real `/research` + `/analyze` round-trip, and `report.{md,docx,pdf}` downloads — `python3 tools/post_deploy_smoke.py https://<host> --key <SILK_API_KEY>`.
- M-20 / M-21 — live WB probe of `LP.LPI.OVRL.XQ` + `IC.IMP.TMBC` and the two Eurostat dataset codes.

---

## الخلاصة بالعربية — أهم ٥ نتائج

1. **خرق عقد عدم الاختلاق على سطر «حدود» العميل (C-1، `silk_render.py:905`).** موضوع
   «الأسعار» في مصالحة الحدود يقبل أي رقم بالدولار كدليلٍ على الحسم، فأي قيمة تجارية
   بالدولار (وهي في كل تقرير تقريباً) تُعيد وسم فجوة سعرٍ حقيقية غير محسومة بأنها
   «حُسمت لاحقاً» — نفس عائلة الدرس ١٢، أُعيد فتحها. الأعلى خطورة لأنه يمسّ المُسلَّم.
2. **نداء كلود المدفوع يسبق زرّ التعطيل (H-1، `silk_engine.py:244`).** تعطيل وكيل
   «ثقافة المستهلك» من لوحة الوكلاء لا يمنع الإنفاق ولا يزيل النتيجة؛ الفحص يقع بعد
   النداء، والسطر `with_websearch=False` ميّت. أُكِّد يدوياً.
3. **تسرّب اسم المزوّد للوحة والتقرير التشغيلي (H-2).** أسماء Volza/Explee/GDELT
   تدخل نموذج العرض الواحد وتُعرض خام على اللوحة، وبوابة الجودة الحتمية لا تملك أي
   نمط مزوّد، وبعثة الأخبار تأمر النموذج بذكر «GDELT». الـPDF للعميل وحده محميّ.
4. **فشل الخدمات الخارجية صامت للمشغّل (H-3، عائلة الدرس ٢٦).** كومتريد والبنك
   الدولي (وWITS وبحث الويب) تتدهور لفجوة معلنة لكنها لا تُكتَب في `ops_errors`
   إطلاقاً — `silk_data_layer.py` لا يستورد `ops_log` مطلقاً. أُكِّد يدوياً.
5. **عائلة ميزانية الرموز (#16) تتكرّر تحت الكاتب المُصلَح (H-6).** المحلّل الشامل بلا
   سُلَّم تصعيد للرموز؛ عند الاقتطاع تعود التقاطعات الخمس «دليل غير كافٍ» — نفس آلية
   الحادثة الأصلية، طبقةً أدنى لم تُقَس بعد.

**تغطية: ٢٢٩ / ٢٢٩ ملف مصدر (١٠٠٪).** المجموعة الهرمتية خضراء (١٣٠٦ نجحت، ١٧
تُخُطّيت) — **رُتبة ١ فقط**؛ الرُتبتان ٢–٣ والفحص الحيّ بانتظار المالك (لا رابط نشر
في الريبو). لم يُصلَح أي شيء في هذا التدقيق — هذه المدخلات لدورة الإصلاح القادمة.

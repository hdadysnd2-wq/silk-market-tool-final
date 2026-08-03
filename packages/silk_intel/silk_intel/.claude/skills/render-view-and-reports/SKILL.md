---
name: render-view-and-reports
description: How numbers become customer-visible output in this repo — the single canonical view-model (silk_render.build_view), the docx/brief/markdown derivatives, sanitization, verdict precedence, and the committed-samples rule. Load before touching silk_render.py, silk_reports.py, web/index.html, or when a report shows a leak, a wrong verdict, or a missing number.
---

# Render view and reports — one view-model, many derivatives

## 1. THE rule: build_view is the only render path

`silk_render.build_view()` (`silk_render.py:695`) is the ONE canonical
view-model. Every surface derives from it:

| Surface | How it consumes the view |
|---|---|
| Dashboard | API attaches `result["view"]`; `web/index.html` renders it |
| Terminal | `silk_render.render_text(view)` (`silk_render.py:827`); `silk_engine.format_result` is literally `render_text(build_view(result))` (`silk_engine.py:635-642`) |
| Word report | `silk_reports.render_docx(view, path)` (`silk_reports.py:1215`) |
| One-page brief | `silk_reports.render_brief(view)` (`silk_reports.py:572`) |
| Markdown report | `silk_reports.render_markdown(view)` (`silk_reports.py:1546`) |
| Mobile brief lines | `view["brief"]` (built inside build_view, `silk_render.py:808-809`) |
| Analysis chat | `silk_render.analysis_context(result)` (`silk_render.py:898`), consumed by `api.py:1372-1373` |

**NEVER add a parallel render path.** The mechanical procedure for exposing a
new number on ANY surface:

1. Add a view key inside `build_view` (or the section builder it calls),
   normalizing through `_dp()` (`silk_render.py:25-34`) so `value / source /
   confidence / note / retrieved_at / status` all travel together.
2. Render that key in each consumer that needs it (dashboard JS, `render_text`,
   the docx/markdown/brief builders).
3. Regenerate `samples/` (§6) and add/extend a hermetic test.

## 2. Provenance is structural, not stylistic

- `components_detail` is built inside the template itself
  (`silk_render.py:730-739`): each component becomes `{name, value, source,
  confidence, retrieved_at, note, status}` — a number without a source line is
  **structurally impossible** in any derivative.
- `_walk_dps` (`silk_render.py:300`) collects every datapoint-shaped node
  (including plural `sources[]` from the Stage-3 research bundle);
  `_provenance` (`silk_render.py:329`) builds the per-source appendix —
  attempted / contributed / up to 3 failure notes per source. No silent failure.
- `_section_dps` (`silk_render.py:262`) is the ONE fact-to-section extractor
  feeding BOTH `_section_coverage` (`silk_render.py:347`) and `_section_status`
  (`silk_render.py:379`) — they cannot disagree by construction.
- `SECTION_THRESHOLDS` (`silk_render.py:368-376`): a section below its
  threshold gets `status="insufficient"`, and the ONLY allowed replacement text
  is `insufficient_line()` (`silk_render.py:398-403`) —
  "بيانات غير كافية لقسم «...» (n/threshold حقائق سوقية) — المصادر المُحاوَلة: ...".
  Never write free-form prose for an insufficient section.

## 3. Verdict precedence — one verdict, never two

Verified at `silk_render.py:37-53` (`_decision`) and `:703-720` (build_view):

1. If the top row carries a **valid weighted-engine decision** —
   `row["decision"]` with `schema` set and no `error` — it REPLACES the jury
   verdict entirely. The jury is demoted to a data-sufficiency line
   (`decision["sufficiency"]` = "بوابة كفاية البيانات: n/m وكلاء أساسيون..."),
   and `stage` reads "silk.decision/v1 — المحرك الموزون §8 (الحكم الوحيد)".
2. Otherwise: AI verdict wins over jury verdict (`ai.get("verdict") or
   jury.get("verdict")`, `silk_render.py:44`).
3. For `/research` results the synthesis verdict is the ONLY verdict — the
   classic 14 sections (and their unfed §8 engine verdict) are never built
   (§5 below).

Guard test: `tests/test_stage5_review_fixes.py:35`
`test_single_authoritative_verdict_everywhere`. Any change here must keep it
green; do not introduce a second verdict string anywhere in a derivative.

## 4. Sanitization lives in the render layer, ONCE

If internal plumbing leaks into a customer report, fix it HERE plus a quality-gate
guard — never by begging the writer prompt to behave:

- `_strip_internal_plumbing` (`silk_render.py:569-580`): rewrites
  `LLMAgent:<key>` / `LLMMissionAgent:<key>` to the Arabic mission name
  (`_mission_label` → `silk_missions.MISSIONS[key]["name"]`,
  `silk_render.py:555`), deletes raw citation tags `dp7` / `[dp7]`
  (`_DP_TAG_RE`, `silk_render.py:531`), collapses double spaces.
- `_strip_raw_json_leak` (`silk_render.py:535-552`): a summary that is entirely
  a raw JSON dump gets its `claim`/`summary`/`value`/`note` extracted, else the
  declared line "تعذّر تفسير رد كلود لهذا البند — بيانات غير مقروءة". Coverage
  across ALL 12 mission keys is asserted by
  `tests/test_wave_p3_writer_diagnostics_and_json_leak.py:357`
  `test_no_raw_json_leaks_into_any_mission_summary_across_all_missions`.
- Mission gap lines are aggregated into `limits` inside `_deep_research_view`
  (`silk_render.py:651-669`) — failed missions AND partial gaps inside
  "successful" missions (`_mission_gap_lines`, `silk_render.py:599`).
- docx-side second line of defense: `_clean_report_text`
  (`silk_reports.py:95-105`) replaces any block starting with `{` or ` ``` `
  with a clean note; `_strip_inline_markdown` (`silk_reports.py:113`) removes
  `**` / `*` / backticks / leading `#`; `_truncate_at_word`
  (`silk_reports.py:81`) forbids mid-word cuts.
- The deterministic quality gate (`silk_quality_gate.run_quality_gate`,
  `silk_quality_gate.py:229`, verdicts `PASS` / `PASS-WITH-WARNINGS` / `FAIL`)
  runs after view build in `api.py:765` and is the regression guard for all of
  the above.

## 5. Docx paths (silk_reports.py)

`render_docx` branches at `silk_reports.py:1233`:

- `view["deep_research"]` present → `_render_research_docx`
  (`silk_reports.py:1149`) EXCLUSIVELY. The classic 14 sections are **never
  built** for research results — wave-8 fix: `/research` always has
  `markets=[]`, so the classic skeleton rendered empty sections ("التغطية
  0.0%") with a contradictory unfed verdict BEFORE the real report. Absent, not
  empty.
- Otherwise → classic path (cover at `:1240`, 14-section TOC at `:1259`).

Mechanics shared by both paths:

- ONE table builder: `_add_table` (`silk_reports.py:632`) — branded header
  (Silk primary color, white text) + zebra rows via oxml `w:shd`
  (python-docx has no top-level API for shading). Branding comes from
  `config/branding.yaml` parsed by the flat stdlib parser `_load_branding`
  (`silk_reports.py:169`) — no PyYAML.
- Markdown tables in writer output are converted to real Word tables:
  `_is_markdown_table_row` (`:126`) + `_render_markdown_table` (`:298`).
- Quality-gate `methodology_notes` are injected programmatically into section 2
  "منهجية البحث ونطاقه" (`silk_reports.py:1059-1063`) — never a cover warning,
  never silence.
- `_stamp_degraded_banner` (`silk_reports.py:59`) prints the red
  "⚠ DEGRADED — نظام الذكاء الاصطناعي غير متاح (...)" banner on degraded runs
  (`view["degraded"]` is hoisted top-level in build_view, `silk_render.py:792`).
- `_assert_production_clean` (`silk_reports.py:30-45`) REFUSES to render a
  non-`SILK_HERMETIC` view containing any of `_HERMETIC_MARKERS =
  ("MagicMock", "example.org", "hermetic", "demo double", "بدائل موسومة")`.
  Consequence: the word "hermetic" inside any error note injected by a test
  poisons derived-report tests — that is exactly why
  `tests/conftest.py:24` raises `OSError("network disabled for offline test")`,
  NOT "...for hermetic test". Keep injected test errors free of those markers.
- Technical appendix: `_docx_technical_appendix` (`silk_reports.py:1126`),
  first 80 citations, full source + retrieved_at for auditors; raw confidence
  numbers appear ONLY there (narrative uses the ✓/◐/○ evidence badge computed
  once in the view, `silk_render.py:640-647`).

## 6. Rule §10.6 — regenerate committed samples with EVERY render change

Source: `docs/VISION.md` §١٠.٦ (~lines 365-370): every output gets a real sample
committed in the repo itself — reviewers open files from the repo, no attachment
channels. PRs #66 / #69 / #71 all carry `samples/` in their diffstats; yours
must too.

Exact commands (both are network-free by design):

```bash
python3 tools/gen_analyze_samples.py    # → samples/report_full_latest.md, report_full_latest.docx,
                                        #   brief_latest.txt, analysis_latest.json
python3 tools/gen_research_sample.py    # → samples/research_report_latest.docx
git add samples/
```

`gen_analyze_samples.py` runs a real deterministic engine pass (seeded store,
socket blocked, `SILK_HERMETIC=1`); `gen_research_sample.py` builds a labeled
mock `/research` view (Spain × dates) through the exact production render path.
Run BOTH after any change to `silk_render.py` or `silk_reports.py`; run the
relevant one for narrower changes, and say which in the PR.

## 7. Bilingual conventions — exact strings are part of the contract

Arabic-first user-facing strings are TESTED BY EXACT STRING. Changing one breaks
tests AND the product contract. Known load-bearing examples:

| String (exact) | Producer | Exact-string test |
|---|---|---|
| "سعر غير مرصود" | `correlation.py:172` | `tests/test_wave4_correlation.py` |
| «من المخزن» (store-served provenance) | store-first agents' notes | `tests/test_store_first_routing.py`, `tests/test_persistent_volume.py:151` |
| "معطّل من إعدادات الوكلاء" | `silk_agents.py:151` | `tests/test_agent_settings_panel.py:85`, `tests/test_wave6_trace.py:153` |
| `insufficient_line()` template "بيانات غير كافية لقسم «...»" | `silk_render.py:398-403` | stage-2B tests |

Rules:
- Numerals are always LTR, even inside RTL Arabic sentences.
- The docx TOC trick: the TOC lines use Latin numerals
  (`doc.add_paragraph(f"{i}. {ttl}")`, e.g. `silk_reports.py:1189-1194` and
  `:1259-1271`) while real section headings use Arabic-Indic numerals
  ("٨. تحليل التجارة"). When a test asserts on a section's body text it must
  search the "٨." heading, not "8.", or it will match the TOC line instead —
  see `tests/test_wave7_live_incident_fixes.py:229-231`.
- New user-facing strings: Arabic first, English mirror where the codebase
  already mirrors (docstrings/comments), and quote them exactly in the test.

## 8. web/index.html — the dashboard consumer

Single self-contained vanilla-JS file; it consumes `result.view` from the API.
Extend the view first (§1), then render it here — never compute new claims in JS.

- Fonts are self-hosted: `<link href="fonts/fonts.css">` (`web/index.html:7-8`),
  files in `web/fonts/*.woff2` (IBM Plex Sans Arabic / IBM Plex Mono / Markazi
  Text). NO CDN — keep it that way.
- localStorage keys (do not rename): `silk_api` (base URL,
  `web/index.html:289`), `silk_lang` (`:321`), `silk_admin_key` (X-API-Key,
  `:336`), `silk_agent_prefs` (`:337`), `silk_hist` (`:338`).
- The settings drawer («إعدادات الوكلاء») builds from `GET /settings/agents`
  (`loadAgentCatalog`, `web/index.html:366`). It must NEVER silently swallow a
  401: on 401 it sets `S.catalogStatus="unauthorized"` (`:375`) and
  `drawDrawer` shows a visible warning (`:700-704`). This is the PR #59
  incident fix ("agent-settings panel silently falls back to legacy list on
  protected deployments") — any refactor must preserve the explicit
  unauthorized state.
- Report/brief downloads go through `fetch` carrying `X-API-Key` then blob
  (`web/index.html:617`) — a plain `<a href>` cannot send the header.

## 9. Pre-merge checklist for any render-layer change

1. `python3 -m pytest tests/ -q` green (hermetic, ~5s).
2. Verdict guard still green: `python3 -m pytest
   tests/test_stage5_review_fixes.py::test_single_authoritative_verdict_everywhere -q`.
3. No new render path — grep your diff for a second place building
   verdict/number strings outside build_view or its existing consumers.
4. Samples regenerated and committed (§6).
5. Exact Arabic strings untouched, or their tests updated deliberately with the
   owner's sign-off (§7).

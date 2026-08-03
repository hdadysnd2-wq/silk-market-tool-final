---
name: analyze-pipeline-debugging
description: DataPoint-first debugging of the /analyze pipeline — reading notes and statuses instead of guessing, the Arabic note dictionary, and the symptom→cause table for empty reports, stale data, wrong years, and self-contradicting numbers. Load whenever an /analyze result looks wrong, empty, stale, or inconsistent.
---

# /analyze debugging — follow the note, never guess

First law: every value is a `DataPoint(value, source, confidence, note,
retrieved_at, status)` (`silk_data_layer.py:111`). Debugging this pipeline means
READING notes and statuses. The system already told you what went wrong — in Arabic,
in the `note` field. Numbers are never guessed, so a `None` is a message, not a bug.

## 1. The status field — three different diagnoses

| `status` | Meaning | Action |
|---|---|---|
| `"fetch_failed"` | Rate limit / network — the data may exist | Retry later; check keys/network; NOT evidence of absence |
| `"no_record"` | The source genuinely has no record | A real, declarable gap — do not retry-loop |
| `"stale"` | Store-served past its freshness window | Value is real but old; background refresh already spawned (SWR) |
| `""` | Fresh live or fresh store hit | Nothing to do |

Related trap: `comtrade_trade()` returns `None` on fetch failure vs `[]` on a
successful-but-empty response (`silk_data_layer.py:~275`). Conflating them
re-creates the "empty report presented as no-data" class of bug.

## 2. The Arabic note dictionary (exact strings → meaning → emitted where)

| Note | Meaning | Emitted |
|---|---|---|
| «تعذّر الجلب (حد معدل/شبكة) — أعد المحاولة» | fetch failed — retry | `silk_agents.py`, ranker |
| «لا سجل في كومتريد لهذه السنة» | genuine no-record for that year | `silk_agents.py` |
| «من المخزن، جُلبت أصلاً <date>» (+ «أقدم من نافذة الحداثة» when stale) | store-served; ORIGINAL retrieved_at preserved | `silk_data_layer_v2.py` store path |
| «سنة {year} لم تُنشر بعد لـ{iso3} — استُخدمت أحدث سنة متاحة» | declared World Bank year fallback | `silk_data_layer.py` |
| «{dropped} سجل بلا قيمة رقمية أُسقط من الجمع» | malformed records dropped from a sum; confidence lowered 0.9→0.7 | TradeFlowAgent |
| `enrichment error: {type}: {e}` | an enrichment wrapper caught an exception | `silk_engine.py:307` `_enrich_error_dp` |
| «سعر غير مرصود — price not observed» | correlation could not match a price | `correlation.py` |
| «معطّل من إعدادات الوكلاء» | agent panel row is off — zero calls attempted | `silk_agents.py` guard |
| `paid agent outside /deepen — skipped (structural guard, no call attempted)` | PAID guard fired | `silk_agents.py` guard |

## 3. Symptom → cause table

| Symptom | Likely cause | Verify | Fix / next step |
|---|---|---|---|
| `classified=False`, `markets=[]` | Resolver weak match (score < 0.7) or chapter-27 exclusion | `hs` DataPoint note shows `weak match (best='X', score=0.NN)` (`silk_hs_resolver.py:142`) or the exclusion note (`EXCLUDED_HS_CHAPTERS`, `:53`) | Better product name, explicit `hs_code=`, or extend `data/hs_codes.csv` (seed is lru-cached — restart after edits) |
| Every score 0.0, every confidence 0.0 | No network / no keys — the honest offline degradation | `GET /health` sources block; `GET /diagnostics` (auth-guarded, fires LIVE probes — use sparingly) | Keys/network; this is correct behavior, not a bug |
| Scores present, confidence low | Missing components; weights renormalized over the present ones | `components_present` ("n/4") and `components_detail` notes per market | Confidence IS the scarcity signal — report it, don't pad it |
| A single market gets suspiciously perfect component scores | `_normalize` hi==lo edge: sole market with data gets 1.0 | Row confidence will be low | Known, documented limitation — the confidence field carries the warning |
| Data looks old | Store-first serving | Note says «من المخزن…» with the ORIGINAL date; `status="stale"` past the window | Working as designed; freshness via `SILK_FRESH_*_DAYS`; force-live only with a real reason |
| Wrong/older year in results | Year fallback: requested year unpublished; walks back ≤4 years (`_MAX_YEAR_FALLBACK`, `silk_market_ranker.py:218`); `data_year = max(year_used of top-3)` feeds all downstream stages | `year_used` per row, `data_year` + `year_fell_back` in the view | Declared and correct — Comtrade publishes late; never hardcode a year |
| Saudi share exactly 0.0 | INFERRED zero (Saudi absent from partner rows), confidence capped 0.6 | Component note | The one deliberate emitted zero — keep its low confidence |
| Market size contradicts the competitor table | world/grand reconciliation: size = max(world row, partner sum); >20% divergence → `xval_note`, competitor confidence 0.9→0.7 | Look for the `xval_note` | The honey/Kuwait 61× incident guard — if you see a contradiction WITHOUT an xval_note, that's a real regression |
| An enrichment section silently empty | REGRESSION: wrappers must emit `_enrich_error_dp`, never silent `[]`/`None` | `view["provenance"]` shows attempted/contributed per source | Fix the wrapper; add the regression test |
| An agent "didn't run" | Panel-disable or PAID guard | The tagged skipped report note (§2) | Re-enable the row / use `/deepen`. Remember PREF_KEY sharing: one row disables several classes (competition, channels, regulatory pairs) |

## 4. The provenance appendix — your silent-failure detector

`view["provenance"]` (built by `_walk_dps` in `silk_render.py`) lists every source
with attempted/contributed counts and failure notes. A source you expected that
appears with attempted=0 never ran at all (guard-skipped or unwired); attempted>0
with contributed=0 ran and failed (read its notes). This is the fastest way to see
which of the ~12 sources actually fed a given report.

## 5. Local repro

```bash
python3 silk_engine.py                       # engine demo, offline-honest
uvicorn api:app --host 0.0.0.0 --port 8000   # API + dashboard
python3 -m pytest tests/test_smoke.py -q     # the ground-truth contract
```
Most `silk_*.py` files have a `__main__` demo. Everything imports offline and
keyless (lazy imports) — an ImportError at import time is itself a regression.

## 6. What NOT to do

- Do not "fix" a `None` by substituting a default — that is fabrication, the one
  unforgivable change in this repo.
- Do not collapse `fetch_failed` / `no_record` / `stale` into one state.
- Do not restamp store-served data with today's date.
- Do not bypass the resolver threshold by lowering 0.7 — pass an explicit
  `hs_code` instead (the designed escape hatch, used by discovery).

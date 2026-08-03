# SPEC v2 — Master Work Order (REFERENCE ONLY)

> **DO NOT EXECUTE THIS FILE AS A COMMAND.**
> This is the reference specification. Execution happens through six sequenced
> commands, each gated on a live artifact. See `docs/DECISIONS.md` for settled
> conflicts and the execution order.
>
> Frozen: 2026-07-16. Any change to this file requires a ledger entry.

---

## Ground rules

- Read `docs/LESSONS.md` + `CLAUDE.md` + relevant skills first.
- Evidence first, never guess.
- **"merged ≠ works"** — only LIVE artifacts close an item.
- Anything not live-proven is reported **NOT DONE**.

---

## Verified live state (owner-side, 2026-07-16)

| Item | State |
|---|---|
| docx export | **WORKS** — owner downloaded a valid file. Oldest bug closed. |
| Volume | Works (`data_dir=/data`) |
| History sidebar | Live |
| Old ephemeral analyses | Gone (expected) |
| "معاينة فورية" button | **STILL LIVE** — removal never executed |
| "حلّل السوق" strings | Leftovers in comments |
| `google_maps` source | Shows "on" in `/health`, appears configured-yet-unused |
| Cost | ~$2.0/run (target ≤ $1.5) |
| Runtime | ~20 min (target < 10 min) |

---

## PART 0 — Triage first (30 min, read-only)

Check ledger / repo / live and report status per item below:
already-done / partially / not-started — **with evidence**. Don't redo finished work.

Also answer: grep the repo — which mission actually calls the `google_maps` source
today? If none, record **"configured-but-unused"** in the ledger.

---

## PART A — UI cleanup (owner decisions, final)

**A1.** DELETE "معاينة فورية" entirely: `#snapBtn`, its flow/panel, `/products/snapshot`
endpoint if nothing internal depends on it (grep callers first; if internals are reused
elsewhere keep the function, delete endpoint + UI). Repo-wide: no orphan strings
("لقطة", "معاينة فورية", stale comments).

**A2.** KEEP "مسح الأسواق"; remove leftover "حلّل السوق" strings/comments.

**A3.** End state: TWO actions (بحث عميق primary, مسح الأسواق secondary) + history sidebar.

---

## PART B — Readability: merchant language, not economist

**B1. WRITER STYLE CONTRACT** (versioned file, injected into writer prompt):

- Audience: صاحب قرار تجاري غير متخصص
- Plain Arabic, short sentences, active voice
- EVERY technical term on FIRST use gets a one-line Arabic gloss in parentheses:
  - HHI (مؤشر يقيس احتكار السوق: فوق 2500 يعني سيطرة لاعب واحد)
  - CAGR (متوسط النمو السنوي)
  - LPI (تقييم البنك الدولي لجودة الشحن من 5)
  - MFN (التعريفة العادية بلا تخفيض)
  - TRACES/CHED (نظام الإخطار الجمركي الأوروبي)
  - EORI (رقم تسجيل المستورد الأوروبي)
- English only in parentheses after Arabic, **never standalone**
- Auto-append مسرد المصطلحات from terms actually used
- Numbers contextualized: "129.6 مليون دولار — نحو 486 مليون ريال"

**B2.** Fold readability into the EXISTING review cycle (no extra paid cycle):
undefined jargon = blocking issue.

**B3.** Lock-test on the real Netherlands blob: glossary present + no standalone
CAGR/HHI/LPI/MFN at first occurrence. Applies to **md AND docx**.

---

## PART C — Google Maps scraper inside the platform (isolate the risk)

**C1.** Deploy `github.com/gosom/google-maps-scraper` as a **SECOND Railway service**
(official Docker image, web-server mode + REST API). Private networking only, never
public. Config: `SILK_GMAPS_SCRAPER_URL`. Do NOT embed in the Python container.
Isolation: if Google blocks that service, main app / DBs / missions untouched.
Give the owner exact Railway console steps (new service from image, its data volume,
private networking).

**C2.** Importers mission: submit ONE scrape job at mission start with localized queries
(NL: `dadels importeur nederland`, `dadels groothandel`, `halal groothandel nederland`,
`arabische supermarkt groothandel`), depth 1, email extraction ON.
ASYNC: submit early, poll; hard timeout 8 min — total runtime must NOT increase
(print before/after).

**C3.** Parse to facts: title, address, phone, EMAIL, website, rating, review_count,
maps link. Dedupe, top ~15. Cache per (market, query-set) — re-runs reuse cached leads.

**C4. FALLBACK CHAIN** (never block a run): scraper down/empty → official Places API
(the unused `google_maps` key finally earns its keep: name/address/phone, no emails)
→ both fail = declared gap. Log which path served.

**C5.** Report output: table **"قائمة مستوردين وموزعين قابلين للتواصل"**
(الاسم | العنوان | الهاتف | الإيميل | الموقع | التقييم | مستوى التوثيق) in the
logistics/entry section, **md AND docx**. Maps-sourced level = ◐ "مرصود عبر خرائط قوقل"
+ one plain line: a Maps listing proves the business exists with contacts, NOT that it
imports Saudi dates. Cross-match web candidates (Ajwa XL, NutsWorld, All4Trade) →
merged rows. **No-fabrication contract untouchable.**

---

## PART D — Report assembly defects (verify status first — may be partially fixed)

**D1.** "حدود هذا البحث" contradicting the body: reconcile limits against the final
fact store before rendering; drop or mark "حُسمت لاحقاً". Fix "…" mid-sentence
truncation (storage vs renderer). Lock-tests.

**D2.** The 5 analyst intersections "بلا أدلة كافية" despite missions contributing:
trace one end-to-end on the real blob, find where facts are lost, fix + lock-test.

**D3.** WGI values (استقرار سياسي / سيادة قانون / جودة تنظيم) absent from §9:
stored-facts check → writer-mapping vs mission-fetch bug, fix accordingly.

---

## PART E — Cost & speed (if not already landed)

**E1.** `usage.db` stage-by-stage: where did $1.6 → $2.0 go? Prime suspect: review
cycles 1 → 2: gate cycle 2 on blocking issues only (`SILK_MAX_REVIEW_CYCLES`,
default 1, cap 2). Check retry storms; cap retries.

**E2.** Haiku routing for extraction/formatting missions (Sonnet only analyst + writer),
per-stage `max_tokens` budgets, prompt caching for shared fact-store context.
Target ≤ $1.5 printed from `llm_usage`.

**E3.** Runtime: profile per-stage wall-time, paste top-3 sinks; run independent
missions concurrently (respect rate limits). Target < 10 min, print before/after.
Per-stage elapsed time in progress UI.

---

## FINAL ACCEPTANCE — one fresh LIVE run proves everything

1. Appears in "بحوثي السابقة" and survives a redeploy.
2. `report.md` + `report.docx` download (200 + opens) — with glossary, plain Arabic,
   importer leads table with real phones/emails.
3. Populated intersections, WGI in §9, reconciled limits, no "…" truncation.
4. Printed: total cost ≤ $1.5, duration < 10 min, per-stage breakdown, which
   leads-path served (scraper/API).
5. `/ops/last-errors` clean; stopping the scraper service does not affect main `/health`.
6. UI: two actions + sidebar, zero orphan strings.

Update `LESSONS.md` (scraping risk must be service-isolated; assembly trusts raw notes
over reconciled facts) + decisions ledger. Report every item honestly:
**DONE-with-artifact / NOT DONE**.

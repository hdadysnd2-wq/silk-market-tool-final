# Phase 3 — Provider adapter readiness (go-live audit)

Phase 3 ("go live, one key at a time") is **config-driven, not a code change**.
`apps/api/app/providers/registry.py` follows one rule: *if a vendor's API key is
set, use the real adapter; otherwise the deterministic mock*. Setting the env var
flips that slot from mock to live. `GET /health` reports `active_provider_summary()`
so you can confirm which adapters are live.

This document is a static readiness audit of the **real** adapters (they are never
exercised by the mock/e2e suites, so they are unproven against the live APIs) plus
the operational runbook for activation.

## Status legend

- ✅ **Solid** — auth, request, parsing, and error→safe-degradation look correct.
- 🔧 **Fixed here** — a bug was fixed in this pass.
- ⚠️ **Verify live** — a contract-level question that cannot be settled offline; check against the vendor's live API before relying on it. **Not guessed at.**

## Per-adapter summary

| Slot | Adapter | Flips live on | Status | Note |
|---|---|---|---|---|
| LLM (vision + judge) | `AnthropicLLMProvider` | `ANTHROPIC_API_KEY` | ✅ / ⚠️ | Auth (`x-api-key` + `anthropic-version`), payload, and vision base64 are correct. `_post` does **not** catch errors, so a live API error (429/5xx/timeout) propagates and crashes the caller — callers (HS resolve, drafting) should wrap it or accept task failure. |
| Comtrade (funnel) | `ComtradeProvider` | `COMTRADE_API_KEY` + `COMTRADE_OFFLINE=0` | ✅ | Robust: broad `except` → cache/fixture fallback (I1). Live calls now **delegate to the engine's `silk_data_layer`** (throttle, backoff, circuit breaker — locked decision #5) under the **per-analysis call budget** (`services/api_budget.py`, ≤150/analysis), locked by `tests/test_comtrade_data_layer.py`. Fixtures remain the offline/CI source. |
| Enrichment | `CoresignalProvider` | `CORESIGNAL_API_KEY` | 🔧 / ⚠️ | **Fixed:** only caught `httpx.HTTPError`, so `search.json()` → `ids[0]` would crash on any non-list/empty shape. Now degrades to `None`. ⚠️ Field names (`employees_count`, `headquarters_city`, `revenue_annual_range`) and the search/collect response shape vary by plan — verify live. |
| Maps | `OutscraperMapsProvider` | `OUTSCRAPER_API_KEY` | 🔧 / ⚠️ | **Fixed:** added non-JSON (`ValueError`) to the degradation path. ⚠️ Outscraper Maps is often **async** (returns a request id to poll); `async=false` requests sync mode — confirm it returns inline results within the 60s timeout, and that `data[0]` is the row list. |
| Email finder | `ApolloEmailFinderProvider` | `APOLLO_API_KEY` | 🔧 / ⚠️ | **Fixed:** degrades to `[]` on any vendor-response surprise. ⚠️ Two contract risks: (1) modern Apollo wants the key in the **`X-Api-Key` header**, not the POST body; (2) `mixed_people/search` typically returns **locked/masked emails** unless revealed via the enrichment endpoint — storing a masked address would hurt deliverability. Verify both live. |
| Email verifier | `ZeroBounceVerifier` | `ZEROBOUNCE_API_KEY` | 🔧 | **Fixed:** degrades to `unknown` (not sendable) on any failure — a hiccup can never leak a sendable verdict. Auth (`api_key` query param), URL, and status map are correct. |
| Sending (cold) | `SmartleadSendingProvider` | `SMARTLEAD_API_KEY` | 🔧 / ⚠️ | **Reworked to Smartlead's campaign model.** Endpoint corrected from the reply endpoint to the **add-lead-to-campaign** API (`POST {SMARTLEAD_BASE}/campaigns/{campaign_id}/leads?api_key=...`, `SMARTLEAD_BASE = https://server.smartlead.ai/api/v1`); `campaign_ref` carries the Smartlead campaign id. Payload reshaped to `{lead_list:[{email, first_name, last_name, custom_fields}], settings:{…}}` — subject/body + the RFC-8058 one-click List-Unsubscribe intent ride in `custom_fields`; `settings` never bypasses the global-block / unsubscribe lists (I4). Endpoint + payload *shape* verified against Smartlead's public docs. ⚠️ Still the live-verification step: the **exact custom-field names** the sequence references and the **sequence template** that must emit `List-Unsubscribe`/`List-Unsubscribe-Post` from them are an UNPROVEN console step — confirmed only by the PR #40 live-smoke (no live send has validated it). Add-leads response shape varies by API version, so result→lead-id mapping is best-effort. |
| Mailbox OAuth (Gmail) | `GmailOAuthProvider` | Google OAuth client id + secret | ✅ | Best-implemented: correct auth-code flow (`access_type=offline`, `prompt=consent` for refresh), refresh keeps the prior refresh token, `verify_mailbox` raises (never silent), send builds base64url MIME with one-click `List-Unsubscribe` (I4). |
| Mailbox OAuth (Microsoft) | `MicrosoftGraphProvider` | Microsoft OAuth client id + secret | ✅ | Mirrors Gmail via the shared `_oauth_http.exchange` (correct `x-www-form-urlencoded` token exchange, revoked-grant → `TokenRefreshError`). Spot-check the Graph `sendMail` payload live. |
| Embeddings | `HashingEmbeddingProvider` | — | ⚠️ | Deterministic placeholder by design (deferred per the prompt). pgvector is wired but not semantically real; fine until a semantic-search feature ships. |

## What was fixed in this pass

The four **data / verification** adapters caught only `httpx.HTTPError`, but response
parsing can raise other exceptions — `response.json()` → `ValueError` on a non-JSON
body (e.g. an HTML error/challenge page), and indexing/`.get` on an unexpected shape
→ `KeyError`/`IndexError`/`TypeError`. Those were **uncaught**, so a single malformed
vendor response would crash the whole market's discovery run instead of degrading.
Each now degrades on any failure to its safe result (`[]` / `None` / `unknown`),
matching `ComtradeProvider`'s existing precedent. The mailbox-OAuth **send**
adapters were left untouched — broadening their error handling could turn a real
send into `accepted=False` and trigger a duplicate.

The **Smartlead cold-send adapter was reworked** in this pass: it now targets the
campaign-based *add-lead-to-campaign* endpoint instead of the reply endpoint (see
its row above). Its add-leads degradation is safer than a raw ESP send would be —
Smartlead dedups a lead within a campaign, so an `accepted=False` retry does not
duplicate a message — but the custom-field/sequence wiring is still UNPROVEN until
the PR #40 live-smoke, so treat the slot as verify-live, not solid.

## Activation order & acceptance gates (from the master prompt)

Flip one key at a time; everything else stays mock.

1. **Anthropic** (vision + judge) → live image→HS on 20 real Saudi products; measure HS top-1/top-3 vs human confirmation.
2. **Comtrade** (+ real ETL world sync) → funnel Stages 1–3 live; **verify ≤150 API calls/analysis** (add budgeting first — see the Comtrade row).
3. **Primary leads provider + ZeroBounce** → live lists for 2 pilot markets; compliance fields (basis, fetched_at, 90-day validity) populated.
4. **Smartlead/Instantly + per-factory OAuth** → configure **SPF + DKIM + DMARC on a dedicated subdomain FIRST**, then warm-up ramp, then a supervised pilot campaign. (The Smartlead adapter is now on the campaign model; the remaining pre-send step is wiring the campaign sequence template to the adapter's custom fields — including the one-click List-Unsubscribe headers — and confirming it with the live-smoke.)

**Pilot acceptance:** confirmed HS; live top-5 with sources+years; ≥1 complete competitor thread (name + observed price + margin); ≥15 verified leads in one market; one approved→sent→tracked campaign; bounce <5%, complaint <0.1%.

## Operational checklist (yours to run in a connected environment)

- [ ] Set each vendor key as an env var (`.env.example` lists them): `ANTHROPIC_API_KEY`, `COMTRADE_API_KEY` (+ `COMTRADE_OFFLINE=0`), `CORESIGNAL_API_KEY` / `APOLLO_API_KEY`, `ZEROBOUNCE_API_KEY`, `SMARTLEAD_API_KEY`, and the Google/Microsoft OAuth client id+secret.
- [ ] Dedicated **sending subdomain** with SPF, DKIM, and DMARC verified **before** any warm-up.
- [ ] Confirm each flip via `GET /health` → `active_provider_summary()`.
- [ ] Resolve the ⚠️ flags above (Smartlead custom-field/sequence-template wiring — endpoint/model now fixed; Apollo header+email-unlock; Coresignal fields; Outscraper async; Comtrade budget) against the live APIs.

> **The keyed live-smoke script now exists**: `apps/api/app/live_smoke.py`. It makes
> one minimal real call per provider — but only for slots whose key is set — so each
> ⚠️ above becomes a pass/fail the moment you configure that key. With no keys it is
> a no-op (every slot `SKIP`, exit 0), and it never sends a cold email (the Smartlead /
> mailbox send path is reported, not exercised — that needs a supervised pilot). Run it
> from `apps/api`:
>
> ```bash
> uv run python -m app.live_smoke          # human-readable table + exit code
> uv run python -m app.live_smoke --json   # machine-readable
> ```

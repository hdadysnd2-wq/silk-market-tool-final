# Launch keys & accounts — everything the operator must supply

Status: **the code is ready and fail-closed; every live path below is one
command away and waiting only on these keys** (audit 2026-08-07 C5). Nothing in
this list is optional-for-launch except where marked. Until a key arrives, the
matching slot degrades to a *declared gap* (never fabricated data, never a mock
send) — that behavior is test-locked.

## 1. Required for the launch gate (one real pilot campaign end to end)

| Purpose | Env var(s) | Where to get it | Used by |
|---|---|---|---|
| LLM (vision, HS classification, drafting, **deep-research report**) | `ANTHROPIC_API_KEY` | console.anthropic.com | api + worker |
| World-trade coverage sync (Stage 1) | `COMTRADE_API_KEY` | UN Comtrade subscription portal | worker (`sync_world_trade`), `make live-sync` |
| Object storage (images, report docx) | `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` (+ optional `S3_REGION`) | Any S3-compatible store (R2 / S3 / MinIO) | api + worker; **the deploy script refuses to run without these** |
| Mailbox sending — Google | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | Google Cloud Console OAuth app (scope `gmail.send` + `gmail.readonly`), publish past testing mode | api (OAuth flow) + worker (send/replies) |
| Mailbox sending — Microsoft (either/or with Google) | `MICROSOFT_OAUTH_CLIENT_ID`, `MICROSOFT_OAUTH_CLIENT_SECRET` | Entra ID app registration (`Mail.Send`, `Mail.Read`) | same |
| Error reporting | `SENTRY_DSN` | sentry.io project | all backend services |

Also required, not a key: a **pilot sender mailbox** (a real Gmail/Microsoft
mailbox on the factory's domain) and that domain's **SPF/DKIM/DMARC** records —
the send path hard-blocks until the built-in DNS check passes.

## 2. Required for full feature depth (can trail the pilot)

| Purpose | Env var(s) | Notes |
|---|---|---|
| Observed competitor prices | `LOCALPRICE_API_KEY` (+ `LOCALPRICE_API_URL` if non-default) | SerpApi. Without it, prices are a declared gap in prod (never mock — C3) |
| Deep-research report (Top 5) | reuses `ANTHROPIC_API_KEY` | ADR-0007. Opt-in, key-gated: 12 Claude missions × Top-5 markets per report — **paid, so it fails closed without the key** (the report renders a "deep research pending API key" declared-gap doc, never fabricated). No NEW key; owner must accept the per-report Claude spend. |
| Stage-2 live enrichment (tariff/PPP) | `MARKET_ENRICHMENT_LIVE=1` | Keyless (World Bank/WITS public APIs) — just flip it on in prod |
| Shipment data (buyer lists) | `VOLZA_API_KEY` (+ `VOLZA_API_URL` if the plan's endpoint differs) | Volza recommended first¹. Without a key, buyer discovery's customs step is a declared gap in prod (never sample importers — C3 pattern); the adapter (`providers/shipments/volza.py`) is ready and waiting on the subscription. |
| Buyer discovery — maps long-tail | `OUTSCRAPER_API_KEY` | |
| Buyer discovery — enrichment | `CORESIGNAL_API_KEY` | |
| Email finding / verification | `APOLLO_API_KEY`, `ZEROBOUNCE_API_KEY` | |
| Cold-send infrastructure (optional channel) | `SMARTLEAD_API_KEY` **+ console work** | Not launchable yet even with the key: the Smartlead campaign-id mapping and webhook wiring are unbuilt (audit C-1/campaigns). Keep `SMARTLEAD_SEQUENCE_VERIFIED` unset so the slot stays fail-closed. |

¹ Shipment-data vendor choice: **Volza** first — API-accessible at the lowest
entry price, good MENA/Asia coverage, importer-level granularity. Alternatives
behind the same adapter seam: **Panjiva** (S&P — premium, best data quality,
higher cost and slower procurement) and **ImportGenius** (mid-price, US-centric
coverage).

## 3. The three one-command proofs

```bash
# 1) Prove every configured vendor adapter once, with real keys (CI, no deploy):
#    GitHub → Actions → "live-smoke" → Run workflow
#    (mirrors the secrets listed above; unset slots SKIP, gated slots report GATED)
gh workflow run live-smoke.yml

# 2) Prove the world-trade sync against live Comtrade for one HS6:
make live-sync HS6=392010          # needs COMTRADE_API_KEY + DATABASE_URL

# 3) Deploy for real (fails closed without the S3 vars above):
./deploy-to-railway.sh
```

## 4. GitHub secrets to mirror (for the live-smoke lane)

`ANTHROPIC_API_KEY`, `COMTRADE_API_KEY`, `LOCALPRICE_API_KEY`,
`LOCALPRICE_API_URL`, `CORESIGNAL_API_KEY`, `OUTSCRAPER_API_KEY`,
`APOLLO_API_KEY`, `ZEROBOUNCE_API_KEY`, `SMARTLEAD_API_KEY`,
`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
`MICROSOFT_OAUTH_CLIENT_ID`, `MICROSOFT_OAUTH_CLIENT_SECRET`.

Leave `SMARTLEAD_SEQUENCE_VERIFIED` unset until the Smartlead sequence template
is verified by a human against a real account (see the gate's docstring in
`apps/api/app/providers/sending/gated.py`).

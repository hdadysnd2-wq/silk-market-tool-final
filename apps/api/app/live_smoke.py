"""Keyed live-smoke harness — turn each provider's readiness ⚠️ into a pass/fail.

Phase 3 activates one provider at a time (locked plan). This script makes one
minimal *real* call per provider **only when its key is configured**, so the
moment you set a key you can confirm auth/shape against the live API instead of
trusting the static readiness audit. With no keys it is a pure no-op: every slot
reports ``SKIP`` and the exit code is 0 (so it is safe to run — and to test —
offline / in CI).

Safety rails:
* It never writes to the database and never sends a cold email. The **sending**
  path (Smartlead / mailbox OAuth) is deliberately NOT exercised — a send would
  cost a real message and needs a supervised pilot, not an automated smoke — so
  those slots report a MANUAL note when configured.
* Data-provider checks are tiny and, for live Comtrade, capped by the per-analysis
  budget. A failure degrades to ``FAIL`` with the error, never a crash.

Run it (from ``apps/api``):

    uv run python -m app.live_smoke          # human-readable table + exit code
    uv run python -m app.live_smoke --json   # machine-readable

Exit code is non-zero only if a *configured* provider's live check FAILED.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.providers.base import LLMMessage

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass
class CheckResult:
    slot: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"slot": self.slot, "status": self.status, "detail": self.detail}


def _truncate(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _check_anthropic(s: Settings) -> CheckResult:
    if not s.anthropic_api_key:
        return CheckResult("anthropic (vision+judge)", SKIP, "no ANTHROPIC_API_KEY")
    try:
        from app.providers.llm.anthropic import AnthropicLLMProvider

        provider = AnthropicLLMProvider(s.anthropic_api_key, s.anthropic_model)
        resp = provider.complete(
            system="Reply with the single word OK.",
            messages=[LLMMessage(role="user", content="Say OK.")],
            max_tokens=8,
        )
        if resp.text and resp.text.strip():
            return CheckResult("anthropic (vision+judge)", PASS, f"model={resp.model} replied")
        return CheckResult("anthropic (vision+judge)", FAIL, "empty response")
    except Exception as exc:  # noqa: BLE001 — a live error is the finding
        return CheckResult("anthropic (vision+judge)", FAIL, _truncate(exc))


def _check_comtrade(s: Settings) -> CheckResult:
    # Comtrade is keyless (a key only raises rate limits); the *live* check runs
    # only when the operator has opted out of offline fixtures.
    if s.comtrade_offline:
        return CheckResult("comtrade (funnel)", SKIP, "COMTRADE_OFFLINE=1 (fixtures)")
    try:
        from app.providers.shipments.comtrade import ComtradeProvider
        from app.services.api_budget import budget_scope

        provider = ComtradeProvider(api_key=s.comtrade_api_key, offline=False)
        with budget_scope(limit=5, label="live_smoke:comtrade"):
            flows = provider.trade_flows("090240", "AE", years=1)  # tea into UAE
        return CheckResult("comtrade (funnel)", PASS, f"{len(flows)} trade-flow record(s)")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("comtrade (funnel)", FAIL, _truncate(exc))


def _check_enrichment(s: Settings) -> CheckResult:
    if not s.coresignal_api_key:
        return CheckResult("coresignal (enrichment)", SKIP, "no CORESIGNAL_API_KEY")
    try:
        from app.providers.enrichment.coresignal import CoresignalProvider

        rec = CoresignalProvider(s.coresignal_api_key).enrich_company("Nestle", "CH", "nestle.com")
        detail = "record returned" if rec else "no record (graceful degrade)"
        return CheckResult("coresignal (enrichment)", PASS, detail)
    except Exception as exc:  # noqa: BLE001
        return CheckResult("coresignal (enrichment)", FAIL, _truncate(exc))


def _check_maps(s: Settings) -> CheckResult:
    if not s.outscraper_api_key:
        return CheckResult("outscraper (maps)", SKIP, "no OUTSCRAPER_API_KEY")
    try:
        from app.providers.maps.outscraper import OutscraperMapsProvider

        rows = OutscraperMapsProvider(s.outscraper_api_key).search_importers(
            "food importers", "AE", limit=1
        )
        return CheckResult("outscraper (maps)", PASS, f"{len(rows)} place(s)")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("outscraper (maps)", FAIL, _truncate(exc))


def _check_apollo(s: Settings) -> CheckResult:
    if not s.apollo_api_key:
        return CheckResult("apollo (email finder)", SKIP, "no APOLLO_API_KEY")
    try:
        from app.providers.email_finding.apollo import ApolloEmailFinderProvider

        found = ApolloEmailFinderProvider(s.apollo_api_key).find_contacts(
            "Nestle", "nestle.com", "CH"
        )
        # A revealed address counts; zero may mean all results were masked (needs
        # the reveal endpoint) — reported, not treated as an auth failure.
        return CheckResult("apollo (email finder)", PASS, f"{len(found)} revealed contact(s)")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("apollo (email finder)", FAIL, _truncate(exc))


def _check_zerobounce(s: Settings) -> CheckResult:
    if not s.zerobounce_api_key:
        return CheckResult("zerobounce (verify)", SKIP, "no ZEROBOUNCE_API_KEY")
    try:
        from app.providers.verification.zerobounce import ZeroBounceVerifier

        result = ZeroBounceVerifier(s.zerobounce_api_key).verify("disposable@example.com")
        return CheckResult("zerobounce (verify)", PASS, f"outcome={result.outcome.value}")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("zerobounce (verify)", FAIL, _truncate(exc))


def _check_smartlead(s: Settings) -> CheckResult:
    # NEVER auto-send: a smoke send costs a real cold email. Report configuration
    # only; the send path is proven by a supervised pilot, not this script.
    if not s.smartlead_api_key:
        return CheckResult("smartlead (cold send)", SKIP, "no SMARTLEAD_API_KEY")
    return CheckResult(
        "smartlead (cold send)",
        SKIP,
        "configured — send NOT smoke-tested (real email); prove via a supervised pilot",
    )


def _check_mailbox_oauth(s: Settings) -> CheckResult:
    configured = []
    if s.google_oauth_client_id and s.google_oauth_client_secret:
        configured.append("gmail")
    if s.microsoft_oauth_client_id and s.microsoft_oauth_client_secret:
        configured.append("microsoft")
    if not configured:
        return CheckResult("mailbox OAuth", SKIP, "no OAuth client credentials")
    # Client creds alone can't send/verify — that needs a connected account's
    # token, which only exists after a factory completes the consent flow.
    return CheckResult(
        "mailbox OAuth",
        SKIP,
        f"{', '.join(configured)} client(s) configured — verify needs a connected mailbox token",
    )


_CHECKS = (
    _check_anthropic,
    _check_comtrade,
    _check_enrichment,
    _check_maps,
    _check_apollo,
    _check_zerobounce,
    _check_smartlead,
    _check_mailbox_oauth,
)


def run_checks(settings: Settings | None = None) -> list[CheckResult]:
    """Run every provider smoke check; offline (no keys) → all SKIP."""
    settings = settings or get_settings()
    return [check(settings) for check in _CHECKS]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    results = run_checks()
    if "--json" in argv:
        print(json.dumps([r.as_dict() for r in results], indent=2))
    else:
        width = max(len(r.slot) for r in results)
        for r in results:
            print(f"  {r.status:4}  {r.slot:<{width}}  {r.detail}")
        passed = sum(r.status == PASS for r in results)
        failed = sum(r.status == FAIL for r in results)
        skipped = sum(r.status == SKIP for r in results)
        print(f"\n  {passed} passed · {failed} failed · {skipped} skipped (no key / manual)")
    # Non-zero only if a *configured* provider actually failed its live check.
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

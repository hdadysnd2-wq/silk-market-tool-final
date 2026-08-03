"""وكيل Explee لسِلك — Silk Explee buyer-discovery agent (PAID / advanced phase).

Best-effort lookup of factories / competitors, decision-makers and B2B contact
emails for a sector or product in a target market, via the Explee account API
(EXPLEE_API_KEY; the account's first ~333 lookups are free, then paid).

دور الوكيل المتأخّر — LATE AGENT ROLE: this agent runs *after* the market has
already been chosen and filtered by the earlier free agents (trade flow,
economics, competition, tariffs). It does not pick markets; it enriches the one
the jury already prioritised, turning a "where" into a concrete "who to email".

الامتثال — COMPLIANCE: personal / manager data (names, roles, emails) is
PERSONAL DATA under GDPR (EU) and PDPL (KSA). It may be used ONLY for legitimate,
relevant B2B outreach — never spam, never resale, never bulk unsolicited mail.
Lawful basis (legitimate interest) requires relevance, opt-out, and minimisation.
If no key is present this agent fabricates NOTHING — it fails gracefully.

Requires a paid account key (EXPLEE_API_KEY). 'requests' is lazy-imported; the
module imports offline and keyless with no side effects (founding principle).
"""
from __future__ import annotations

import logging
import os

from silk_data_layer import DataPoint, _today
from silk_agents import BaseAgent, AgentReport

log = logging.getLogger(__name__)

# نقطة نهاية Explee — overridable via env so a format change needs no code edit.
_EXPLEE_URL = os.environ.get(
    "EXPLEE_API_URL", "https://api.explee.com/v1/search").strip()
_TIMEOUT = 30

# ملاحظة الامتثال المختصرة — short compliance banner reused in summaries.
_COMPLIANCE = ("COMPLIANCE: personal/manager data is GDPR(EU)/PDPL(KSA) "
               "personal data — legitimate B2B outreach only, not spam.")


def discover_buyers(query: str, market: str) -> list[DataPoint]:
    """اكتشاف المشترين — best-effort factories/competitors + decision-makers + emails.

    Calls Explee with EXPLEE_API_KEY for a sector/product `query` in `market`.
    No key -> single DataPoint(None, 0.0, "<requires key>"). With a key, attempts
    defensively and parses companies/contacts; any failure (network, format,
    empty) -> graceful None DataPoint. NEVER fabricates people/emails.
    """
    key = os.environ.get("EXPLEE_API_KEY", "").strip()
    if not key:
        log.warning("EXPLEE_API_KEY not set — Explee buyer discovery unavailable")
        return [DataPoint(None, "Explee", 0.0,
                          "explee requires an account key (EXPLEE_API_KEY)",
                          _today())]
    q = (query or "").strip()
    mkt = (market or "").strip()
    if not q or not mkt:
        return [DataPoint(None, "Explee", 0.0,
                          "empty query or market — no Explee lookup", _today())]
    try:
        import requests  # lazy: only needed when a key is present
    except ImportError:
        log.warning("requests unavailable — Explee buyer discovery unavailable")
        return [DataPoint(None, "Explee", 0.0,
                          "requests unavailable / no network", _today())]
    try:
        r = requests.get(
            _EXPLEE_URL,
            params={"query": q, "market": mkt, "country": mkt},
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception as e:  # noqa: BLE001 — paid 3rd-party API; never raise
        note = f"Explee unavailable: {type(e).__name__}: {e}"
        log.warning(note)
        return [DataPoint(None, "Explee", 0.0, note, _today())]

    findings = _parse_companies(payload)
    if not findings:
        log.warning("Explee returned no parseable companies for %r in %r", q, mkt)
        return [DataPoint(None, "Explee", 0.0,
                          f"no companies/contacts returned for '{q}' in {mkt}",
                          _today())]
    return findings


def _parse_companies(payload: object) -> list[DataPoint]:
    """تحليل الشركات — pull companies + decision-makers/emails defensively.

    Explee's exact schema is not contractually stable, so accept several common
    shapes (list, {results|data|companies: [...]}) and only emit a DataPoint when
    real fields are present. Returns [] when nothing usable is found (no guesses).
    """
    if isinstance(payload, dict):
        rows = (payload.get("results") or payload.get("data")
                or payload.get("companies") or [])
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    findings: list[DataPoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or row.get("company")
                or row.get("companyName") or row.get("title"))
        if not name:
            continue
        contact = _first_contact(row)
        note_parts = [str(name)]
        if row.get("country") or row.get("market"):
            note_parts.append(f"({row.get('country') or row.get('market')})")
        if contact:
            note_parts.append("— " + contact)
        findings.append(DataPoint(
            value=str(name), source="Explee", confidence=0.6,
            note=" ".join(note_parts) + f" | {_COMPLIANCE}",
            retrieved_at=_today()))
    return findings


def _first_contact(row: dict) -> str:
    """أوّل صانع قرار — best-effort 'Role Name <email>' from a company row, or ''.

    Returns "" rather than inventing anything when no real contact field exists.
    """
    contacts = (row.get("contacts") or row.get("decisionMakers")
                or row.get("people") or [])
    person = contacts[0] if isinstance(contacts, list) and contacts else row
    if not isinstance(person, dict):
        return ""
    pname = (person.get("name") or person.get("fullName")
             or person.get("contactName") or "")
    role = (person.get("role") or person.get("title")
            or person.get("position") or "")
    email = (person.get("email") or person.get("contactEmail") or "")
    bits = [b for b in (role, pname) if b]
    label = " ".join(bits)
    if email:
        label = (label + f" <{email}>") if label else f"<{email}>"
    return label.strip()


class ExpleeAgent(BaseAgent):
    """وكيل Explee — late, paid buyer-discovery agent (factories/contacts/emails).

    Runs AFTER market filtering to enrich the chosen market with real companies
    and B2B decision-maker contacts. COMPLIANCE: emits personal data subject to
    GDPR(EU)/PDPL(KSA) for legitimate B2B outreach only — not spam. Fabricates
    nothing: no key / network fail / empty -> failed report.
    """

    PAID = True
    PREF_KEY = "contacts"
    SOURCE = "Explee"

    def __init__(self) -> None:
        super().__init__("ExpleeAgent")

    def _execute(self, task: dict) -> AgentReport:
        """اكتشاف مشترين للسوق المختارة — discover buyers for the filtered market.

        task keys: query (sector/product), market (target market name/ISO).
        """
        query = task.get("query", "")
        market = task.get("market", "")
        findings = discover_buyers(query, market)
        real = [f for f in findings if f.value is not None]
        failed = not real
        if failed:
            summary = (f"لا توجد بيانات مشترين — no Explee buyer data. "
                       f"{findings[0].note if findings else ''} | {_COMPLIANCE}")
        else:
            summary = (f"{len(real)} company/contact record(s) for '{query}' "
                       f"in {market} (late agent, after market filtering). "
                       f"{_COMPLIANCE}")
        return AgentReport(self.name, findings, failed, summary)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk ExpleeAgent — late paid layer; degrades gracefully keyless "
          "(no fabricated people/emails)")
    report = ExpleeAgent().run({"query": "dates packaging", "market": "DEU"})
    flag = "FAILED" if report.failed else "ok"
    print(f"  [{flag}] {report.agent_name}: {report.summary}")
    for f in report.findings:
        print(f"    value={f.value} conf={f.confidence} note={f.note}")

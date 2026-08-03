"""وكيل فولزا لسِلك — Silk Volza research agent (PAID / advanced phase).

Surfaces named importers (and exporters) of an HS code into a market from bills
of lading via the Volza API. Volza is a PAID subscription, so this layer is
ADVANCED and key-gated:

  - No VOLZA_API_KEY  -> failed report + DataPoint(None, 0.0, "requires a paid
    subscription"). No network call is attempted.
  - Key present       -> a defensive best-effort request; on any failure /
    empty / format change -> graceful None. Company NAMES are read only from the
    real response and NEVER fabricated (founding principle).

'requests' is lazy-imported inside the method so `import silk_volza_agent` works
offline with no key.
"""
from __future__ import annotations

import logging
import os

from silk_data_layer import DataPoint, ISO3_TO_M49, _today
from silk_agents import BaseAgent, AgentReport

log = logging.getLogger(__name__)

# نقطة نهاية فولزا (قابلة للتهيئة) — Volza endpoint; overridable via env because
# the paid API path/host may differ per subscription/plan.
_VOLZA_URL = os.environ.get(
    "VOLZA_API_URL", "https://api.volza.com/v1/import/companies").strip()
_TIMEOUT = 30
_NO_KEY_NOTE = "Volza requires a paid subscription (VOLZA_API_KEY)"


def importers_by_name(
    hs_code: str,
    market: object,
    partner: str = "SAU",
) -> list[DataPoint]:
    """مستوردون بالاسم — named importers of an HS code into a market (PAID).

    Best-effort Volza API call keyed on os.environ['VOLZA_API_KEY']. With no key
    returns a single failed DataPoint (no network call). With a key, attempts the
    request defensively and parses named importers; on any error / empty result
    returns one provenance-tagged None. Company names come only from the real
    response — never fabricated.
    """
    key = os.environ.get("VOLZA_API_KEY", "").strip()
    if not key:
        log.warning("VOLZA_API_KEY not set — Volza is a paid subscription")
        return [DataPoint(None, "Volza", 0.0, _NO_KEY_NOTE, _today())]

    try:
        import requests  # lazy: only needed when a key is present
    except ImportError as e:  # pragma: no cover — requests is a core dep
        log.warning("requests unavailable for Volza fetch: %s", e)
        return [DataPoint(None, "Volza", 0.0,
                          f"requests unavailable: {e}", _today())]

    params = {
        "hsCode": str(hs_code),
        "country": str(market),          # destination market (importer side)
        "originCountry": str(partner),   # exporter / partner origin
    }
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        r = requests.get(_VOLZA_URL, params=params, headers=headers,
                         timeout=_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:  # noqa: BLE001 — paid API is opaque; never raise
        note = (f"Volza fetch failed for HS{hs_code} {partner}->{market}: "
                f"{type(e).__name__}: {e}")
        log.warning(note)
        return [DataPoint(None, "Volza", 0.0, note, _today())]

    names = _parse_importer_names(payload)
    if not names:
        note = f"Volza: no named importers parsed for HS{hs_code} into {market}"
        log.warning(note)
        return [DataPoint(None, "Volza", 0.0, note, _today())]
    return [
        DataPoint(name, "Volza", 0.85,
                  f"importer of HS{hs_code} into {market} from {partner} "
                  "(bill of lading)", _today())
        for name in names
    ]


def _parse_importer_names(payload: object) -> list[str]:
    """استخراج أسماء المستوردين — pull importer company names from a Volza reply.

    Volza response shapes vary by plan; probe the common containers defensively.
    Returns a de-duplicated list of non-empty name strings (order preserved), or
    [] if nothing parseable is found. Never invents a name.
    """
    if isinstance(payload, dict):
        rows = (payload.get("data") or payload.get("results")
                or payload.get("companies") or [])
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            name = row.strip()
        elif isinstance(row, dict):
            raw = (row.get("importerName") or row.get("importer")
                   or row.get("companyName") or row.get("name") or "")
            name = str(raw).strip()
        else:
            name = ""
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


class VolzaAgent(BaseAgent):
    """وكيل فولزا — named importers/exporters from bills of lading (PAID, advanced).

    يرث BaseAgent (الموجة ٢): PAID=True يعني الحصر البنيوي داخل /deepen —
    خارجه يستحيل الاستدعاء حتى مع مفتاح مضبوط.
    """

    PAID = True
    PREF_KEY = "importers"
    SOURCE = "Volza"

    def __init__(self) -> None:
        super().__init__("VolzaAgent")

    def _execute(self, task: dict) -> AgentReport:
        """مستوردون بالاسم من فولزا — named importers for an HS code into a market.

        task keys: hs_code (or product as a label), market (M49/ISO3 of the
        destination), partner (origin ISO3, default 'SAU'). With no paid key the
        report is failed with a clear 'requires subscription' note; never invents
        company names.
        """
        hs = task.get("hs_code") or task.get("product")
        partner = task.get("partner", "SAU")
        market = task.get("market") or task.get("market_m49") or task.get("iso3")
        if not hs or not market:
            return AgentReport(
                self.name, [], True,
                "لا يوجد HS أو سوق — missing hs_code/product or market")

        findings = importers_by_name(str(hs), market, partner)
        real = [f for f in findings if f.value is not None]
        failed = not real
        if failed:
            note = findings[0].note if findings else _NO_KEY_NOTE
            summary = f"لا توجد بيانات فولزا — no Volza data ({note})"
        else:
            summary = (f"{len(real)} named importer(s) of HS{hs} into "
                       f"{market} from {partner}")
        return AgentReport(self.name, findings, failed, summary)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk VolzaAgent — PAID/advanced; degrades gracefully without "
          "VOLZA_API_KEY (no fabricated company names)")
    report = VolzaAgent().run(
        {"hs_code": "5201", "market": 156, "partner": "SAU"})
    flag = "FAILED" if report.failed else "ok"
    print(f"  [{flag}] {report.agent_name}: {report.summary}")
    for f in report.findings:
        print(f"    value={f.value} conf={f.confidence} note={f.note}")
    _ = ISO3_TO_M49  # imported for downstream market-code resolution / symmetry.

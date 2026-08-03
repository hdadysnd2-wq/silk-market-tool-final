"""وكيل خرائط جوجل لسِلك — Silk Google Maps research agent (docx layer 6).

Finds real businesses BY NAME — factories, distributors, competitors — with
their ratings via the Google Places Text Search API. Requires a real key
(GOOGLE_MAPS_API_KEY); with no key OR a network failure it returns a
provenance-tagged None and never invents businesses (founding principle).

Reads GOOGLE_MAPS_API_KEY from the environment (a .env loader already runs in
silk_data_layer). 'requests' is lazy-imported inside methods so the module
imports offline and keyless.
"""
from __future__ import annotations

import logging
import os

from silk_data_layer import DataPoint, _today
from silk_agents import BaseAgent, AgentReport

log = logging.getLogger(__name__)

# بحث نصي في أماكن جوجل — Google Places Text Search endpoint.
_PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_TIMEOUT = 30


def find_places(query: str, region: str | None = None) -> list[DataPoint]:
    """ابحث عن أماكن حقيقية — real businesses by name + rating from Google Maps.

    Each Places result -> DataPoint(value={name, rating, address,
    user_ratings_total}). No key -> a single DataPoint(None, 0.0, ...). On
    network/API failure or empty -> [] (caller flags it). Never fabricates.
    """
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        log.warning("GOOGLE_MAPS_API_KEY not set — Google Maps unavailable")
        return [DataPoint(None, "Google Maps", 0.0,
                          "Google Maps requires GOOGLE_MAPS_API_KEY", _today())]
    q = (query or "").strip()
    if not q:
        return [DataPoint(None, "Google Maps", 0.0,
                          "empty query — no search", _today())]
    try:
        import requests  # lazy: keeps import offline-safe and keyless
    except ImportError:
        log.warning("requests not installed — Google Maps unavailable")
        return [DataPoint(None, "Google Maps", 0.0,
                          "requests unavailable", _today())]
    params = {"query": q, "key": key}
    if region:
        params["region"] = region  # ccTLD bias, e.g. 'ma' for Morocco
    try:
        r = requests.get(_PLACES_URL, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:  # noqa: BLE001 — never raise to caller
        log.warning("Google Maps fetch failed (q=%r, region=%s): %s", q, region, e)
        try:  # عائلة C (Wave 1.5): إعلان الفشل للمشغّل.
            import silk_ops_log
            silk_ops_log.record_service_failure(
                "maps", f"Google Maps fetch failed (q={q!r}): {e}")
        except Exception:  # noqa: BLE001
            pass
        return [DataPoint(None, "Google Maps", 0.0,
                          f"Google Maps fetch failed: {e}", _today())]
    status = payload.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        note = f"Google Maps API status={status}: {payload.get('error_message', '')}".strip()
        log.warning(note)
        return [DataPoint(None, "Google Maps", 0.0, note, _today())]
    results = payload.get("results") or []
    findings: list[DataPoint] = []
    for place in results:
        name = place.get("name")
        if not name:
            continue
        findings.append(DataPoint(
            {
                "name": name,
                "rating": place.get("rating"),
                "address": place.get("formatted_address"),
                "user_ratings_total": place.get("user_ratings_total"),
                # تصنيف جوجل الفعلي للمكان — يفرّق تجزئة/مطعماً عن جهة
                # جملة محتملة (بلاغ مالك حقيقي: محلات عصير ظهرت "مستوردين").
                "types": place.get("types") or [],
            },
            "Google Maps", 0.7,
            f"place '{name}' for query '{q}'" + (f" region={region}" if region else ""),
            _today()))
    if not findings:
        return [DataPoint(None, "Google Maps", 0.0,
                          f"no places found for '{q}'", _today())]
    return findings


class MapsAgent(BaseAgent):
    """وكيل الخرائط — named factories/distributors/competitors + ratings."""

    PAID = False
    PREF_KEY = "maps"

    def __init__(self) -> None:
        super().__init__("MapsAgent")

    def _execute(self, task: dict) -> AgentReport:
        """جد لاعبي السوق بالاسم — locate market players by name on Google Maps.

        task keys: query (product+market, e.g. 'تمور موزعون المغرب'),
                   region (ccTLD bias like 'ma', optional). Missing key /
                   network fail -> failed report, never a fabricated business.
        """
        query = task.get("query", "")
        region = task.get("region")
        findings = find_places(query, region)
        real = [f for f in findings if f.value is not None]
        if not real:
            note = findings[0].note if findings else "no query"
            return AgentReport(self.name, findings, True,
                               f"لا توجد أماكن — no Google Maps data ({note})")
        return AgentReport(self.name, real, False,
                           f"{len(real)} place(s) for '{query}'"
                           + (f" region={region}" if region else ""))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk MapsAgent — degrades gracefully offline / without key (no fabricated data)")
    report = MapsAgent().run({"query": "تمور موزعون المغرب", "region": "ma"})
    flag = "FAILED" if report.failed else "ok"
    print(f"  [{flag}] {report.agent_name}: {report.summary}")
    for f in report.findings:
        print(f"    value={f.value} conf={f.confidence} note={f.note}")

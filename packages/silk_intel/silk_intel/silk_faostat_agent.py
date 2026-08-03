"""وكيل فاوستات لسِلك — Silk FAOSTAT food consumption/production agent.

Best-effort per-capita food supply / production from FAOSTAT REST
(faostatservices.fao.org). Real data only: on auth-required / empty / format
change / network failure it returns a provenance-tagged DataPoint(value=None,
confidence=0.0) and logs a warning — it NEVER guesses a number.

AUTH CAVEAT — تنبيه المصادقة: FAOSTAT recently added authentication to parts of
its public API. Anonymous requests may return 401/403 or an HTML/error body. We
detect that and degrade gracefully; we do not embed or invent credentials.

بلاغ حي (تشغيلة تمور/هولندا الثالثة، 401 متكرر): قاطع دارة داخل العملية —
أول 401/403 يعطّل المحاولات اللاحقة تلقائياً لبقية عمر العملية (فجوة معلنة
نظيفة بدل محاولة HTTP فاشلة في كل بعثة/تشغيلة)، و`SILK_DISABLE_FAOSTAT=1`
يعطّل المصدر صراحة بلا أي محاولة إطلاقاً.
"""
from __future__ import annotations

import logging
import os

import requests

from silk_data_layer import DataPoint, _today
from silk_agents import BaseAgent, AgentReport

log = logging.getLogger(__name__)

# قاطع الدارة — يُضبط عند أول 401/403 في هذه العملية؛ يحمل نص الحالة
# للملاحظة المعلنة. reset_auth_block() للاختبارات (وإعادة التفعيل يدوياً).
_auth_blocked: str | None = None


def reset_auth_block() -> None:
    """أعد فتح قاطع الدارة — test/ops helper؛ لا يُستدعى في مسار تشغيل عادي."""
    global _auth_blocked
    _auth_blocked = None


def _disabled_note(iso3: str, item: str) -> str | None:
    """سبب التعطيل الحالي إن وُجد — kill switch البيئة أولاً ثم قاطع الدارة."""
    if os.environ.get("SILK_DISABLE_FAOSTAT", "").strip() in ("1", "true", "yes"):
        return (f"FAOSTAT معطَّل صراحة (SILK_DISABLE_FAOSTAT) — فجوة معلنة "
                f"لـ{iso3}/{item}، لا محاولة جلب")
    if _auth_blocked:
        return (f"FAOSTAT يتطلب مصادقة حالياً ({_auth_blocked} في نداء سابق "
                f"بهذه العملية) — عُطّل تلقائياً؛ فجوة معلنة لـ{iso3}/{item}")
    return None

# قاعدة فاوستات — FAOSTAT data endpoint (domain filled per call).
_FAOSTAT_BASE = "https://faostatservices.fao.org/api/v1/en/data"
_TIMEOUT = 30

# النطاق الافتراضي — Food Balance Sheets domain carries per-capita supply.
_DEFAULT_DOMAIN = "FBS"
# العنصر الافتراضي — element 645 = Food supply quantity (kg/capita/yr).
_DEFAULT_ELEMENT = "645"

# ISO3 -> FAOSTAT area code (M49-based, small best-effort dict).
ISO3_TO_FAOSTAT_AREA = {
    "SAU": 194, "ARE": 225, "QAT": 179, "KWT": 118, "OMN": 221, "BHR": 13,
    "JOR": 112, "LBN": 121, "EGY": 59, "MAR": 143, "TUN": 222, "DZA": 4,
    "LBY": 124, "SDN": 276, "YEM": 249, "IRQ": 103, "IRN": 102,
    "TUR": 223, "PAK": 165, "IND": 100, "BGD": 16, "LKA": 38, "IDN": 101,
    "MYS": 131, "THA": 216, "VNM": 237, "PHL": 171, "CHN": 351, "JPN": 110,
    "KOR": 117, "USA": 231, "CAN": 33, "MEX": 138, "BRA": 21, "GBR": 229,
    "DEU": 79, "FRA": 68, "ITA": 106, "ESP": 203, "NLD": 150, "RUS": 185,
    "ZAF": 202, "NGA": 159, "KEN": 114, "ETH": 238,
}


def per_capita_supply(
    iso3: str,
    item: str,
    year: int | None = None,
    element: str = _DEFAULT_ELEMENT,
    domain: str = _DEFAULT_DOMAIN,
) -> DataPoint:
    """نصيب الفرد من سلعة غذائية — FAOSTAT per-capita supply for one item.

    Best-effort; returns DataPoint(value=None, confidence=0.0, note=...) on any
    failure (auth/empty/format/network) — never fabricates.
    """
    disabled = _disabled_note(iso3, item)
    if disabled:
        log.info(disabled)  # info لا warning — تعطيل مقصود معلن، ليس عطلاً جديداً
        return DataPoint(None, "FAOSTAT", 0.0, disabled, _today())

    area = ISO3_TO_FAOSTAT_AREA.get(iso3.upper())
    if area is None:
        note = f"FAOSTAT unavailable: unknown area for ISO3 '{iso3}' (no mapping)"
        log.warning(note)
        return DataPoint(None, "FAOSTAT", 0.0, note, _today())

    params = {
        "area": str(area),
        "element": str(element),
        "show_codes": "true",
        "show_unit": "true",
        "output_type": "objects",
    }
    if year is not None:
        params["year"] = str(year)

    url = f"{_FAOSTAT_BASE}/{domain}"
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        if r.status_code in (401, 403):
            global _auth_blocked
            _auth_blocked = f"HTTP {r.status_code}"  # قاطع الدارة — لا محاولات لاحقة
            note = (f"FAOSTAT unavailable: HTTP {r.status_code} for {iso3}/{item} "
                    "(auth now required?) — عُطّلت المحاولات اللاحقة تلقائياً "
                    "لهذه العملية")
            log.warning(note)
            return DataPoint(None, "FAOSTAT", 0.0, note, _today())
        r.raise_for_status()
        payload = r.json()
    except ValueError as e:  # non-JSON body -> likely auth/format change
        note = f"FAOSTAT unavailable: non-JSON response for {iso3}/{item}: {e} (may require auth)"
        log.warning(note)
        return DataPoint(None, "FAOSTAT", 0.0, note, _today())
    except Exception as e:  # noqa: BLE001 — network/HTTP; never raise to caller
        note = f"FAOSTAT unavailable: fetch failed for {iso3}/{item}: {e} (may require auth)"
        log.warning(note)
        try:  # عائلة C (Wave 1.5): إعلان الفشل للمشغّل.
            import silk_ops_log
            silk_ops_log.record_service_failure("faostat", note)
        except Exception:  # noqa: BLE001
            pass
        return DataPoint(None, "FAOSTAT", 0.0, note, _today())

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not rows:
        note = f"FAOSTAT unavailable: empty data for {iso3}/{item} {year or ''} (may require auth)"
        log.warning(note)
        return DataPoint(None, "FAOSTAT", 0.0, note, _today())

    want = item.strip().lower()
    chosen = None
    for row in rows:
        ritem = str(row.get("Item", "")).strip().lower()
        if ritem == want or want in ritem:
            chosen = row
            break
    if chosen is None:
        note = f"FAOSTAT unavailable: item '{item}' not found for {iso3} (may require auth)"
        log.warning(note)
        return DataPoint(None, "FAOSTAT", 0.0, note, _today())

    raw = chosen.get("Value")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        note = f"FAOSTAT unavailable: non-numeric value for {iso3}/{item}: {raw!r} (may require auth)"
        log.warning(note)
        return DataPoint(None, "FAOSTAT", 0.0, note, _today())

    unit = chosen.get("Unit", "")
    yr = chosen.get("Year", year)
    note = f"{chosen.get('Item', item)} element={element} year={yr} unit={unit}"
    return DataPoint(value, "FAOSTAT", 0.85, note, _today())


class FaostatAgent(BaseAgent):
    """وكيل فاوستات — per-capita food consumption/production for a market."""

    PAID = False

    def __init__(self) -> None:
        super().__init__("FaostatAgent")

    def _execute(self, task: dict) -> AgentReport:
        """نصيب الفرد الغذائي — FAOSTAT per-capita supply for the task's item."""
        iso3 = task.get("iso3") or task.get("country")
        item = task.get("item") or task.get("product")
        year = task.get("year")
        element = task.get("element", _DEFAULT_ELEMENT)
        if not iso3 or not item:
            return AgentReport(
                self.name, [], True,
                "لا يوجد ISO3/سلعة — missing iso3/country or item, cannot query FAOSTAT")
        dp = per_capita_supply(str(iso3), str(item), year, element=str(element))
        failed = dp.value is None
        summary = (f"FAOSTAT unavailable for {iso3}/{item} (best-effort)"
                   if failed else f"FAOSTAT per-capita supply {dp.value} for {iso3}/{item}")
        return AgentReport(self.name, [dp], failed, summary)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk FAOSTAT agent — best-effort, degrades gracefully offline / under auth")
    report = FaostatAgent().run({"iso3": "SAU", "item": "Dates", "year": 2021})
    flag = "FAILED" if report.failed else "ok"
    print(f"  [{flag}] {report.agent_name}: {report.summary}")
    for f in report.findings:
        print(f"    value={f.value} conf={f.confidence} note={f.note}")

"""محرّك خط الاتجاه متعدد السنوات لسِلك — Silk multi-year import-trend engine (wave 6).

يجيب عن سؤال «سنوات الدراسة» (لا سنة واحدة): كيف تطوّر استيراد السوق لهذا الرمز
عبر مدى سنوات؟ — سلسلة سنوية + نسبة نمو + نمو سنوي مركّب (CAGR).

**صفر مصادر جديدة:** يعمل حصراً على UN Comtrade عبر `silk_data_layer.comtrade_trade`
القائمة — نفس انضباط `silk_discovery` (اختبار AST بنيوي يثبته). **سنة بلا بيانات =
فجوة معلنة (`value=None`) لا صفر مختلق** — صفرٌ هنا يولّد نسبة نمو مختلقة لاحقاً
(المبدأ التأسيسي). أقل من نقطتين مرصودتين => النمو/CAGR = `None` بصدق، لا تخمين.

Answers the "study years" question (not a single snapshot): how did the market's
imports of this HS evolve across a span of years — a yearly series plus growth %
and CAGR. Zero new data sources (Comtrade only). A year with no data is a declared
gap (value=None), never a fabricated 0; fewer than two observed points => growth
and CAGR are honestly None, never guessed.
"""
from __future__ import annotations

import logging

from silk_data_layer import DataPoint, comtrade_trade, primary_value, _today

log = logging.getLogger(__name__)

_DEFAULT_SPAN = 5        # مدى الدراسة الافتراضي (٥ سنوات) — default study span
_MAX_SPAN = 10          # سقف — cap to bound Comtrade calls


def _year_total(hs_code: str, market_m49: object, year: int,
                flow: str = "M") -> float | None:
    """إجمالي استيراد رمز في سوق لسنة واحدة — total import value for one year.

    سجل بلا `primaryValue` رقمية يُسقَط ولا يُعدّ صفراً (المبدأ التأسيسي):
    صفرٌ مختلق هنا يولّد نسبة نمو مختلقة في الحساب التالي. لا سجلات أو لا قيم
    رقمية => `None` (فجوة معلنة، لا صفر). Never sums a missing record as 0.
    """
    recs = comtrade_trade(hs_code, market_m49, year, flow=flow, partner=0) or []
    vals = [v for v in (primary_value(r) for r in recs) if v is not None]
    return sum(vals) if vals else None


def growth_pct(series: list[tuple[int, float | None]]) -> float | None:
    """نسبة النمو بين أول وآخر قيمة مرصودة — over first & last OBSERVED points.

    أقل من نقطتين مرصودتين، أو قيمة أساس ≤0 => `None` (فجوة معلنة، لا تخمين).
    دالة نقية قابلة للاختبار. Pure/testable; declares the gap, never guesses.
    """
    obs = [(y, v) for y, v in series if v is not None]
    if len(obs) < 2:
        return None
    first, last = obs[0][1], obs[-1][1]
    if first <= 0:
        return None
    return round(100.0 * (last - first) / first, 1)


def cagr_pct(series: list[tuple[int, float | None]]) -> float | None:
    """النمو السنوي المركّب بين أول وآخر سنة مرصودة — CAGR over the observed span.

    يتخطّى سنوات الفجوة (يعتمد أول وآخر سنة *مرصودة* والفارق بينهما). أقل من
    نقطتين، أو مدى/قيم غير صالحة => `None`. Skips gap years; None if unresolvable.
    """
    obs = [(y, v) for y, v in series if v is not None]
    if len(obs) < 2:
        return None
    (y0, first), (y1, last) = obs[0], obs[-1]
    n = y1 - y0
    if n <= 0 or first <= 0 or last <= 0:
        return None
    return round(((last / first) ** (1.0 / n) - 1.0) * 100.0, 1)


def import_trend(hs_code: str, market_m49: object, end_year: int,
                 span: int = _DEFAULT_SPAN) -> dict:
    """خط اتجاه استيراد سوق لرمز عبر مدى سنوات — multi-year import trend.

    نداء Comtrade واحد لكل سنة (يتدهور بأمان إلى `[]`)؛ سنة بلا بيانات => قيمة
    `None` (فجوة معلنة) لا صفر. Returns:
        {hs_code, market_m49, years, series:[{year,value,observed}],
         growth_pct, cagr_pct, observed_years, gap_years, source,
         retrieved_at, note}
    All values provenance-consistent; nothing is fabricated.
    """
    span = max(2, min(int(span or _DEFAULT_SPAN), _MAX_SPAN))
    years = list(range(end_year - span + 1, end_year + 1))
    pairs: list[tuple[int, float | None]] = []
    series: list[dict] = []
    for y in years:
        v = _year_total(hs_code, market_m49, y)
        pairs.append((y, v))
        series.append({"year": y, "value": v, "observed": v is not None})

    observed_years = [y for y, v in pairs if v is not None]
    gap_years = [y for y, v in pairs if v is None]
    g, c = growth_pct(pairs), cagr_pct(pairs)
    if len(observed_years) < 2:
        note = (f"بيانات غير كافية لخط الاتجاه — "
                f"{len(observed_years)}/{len(years)} سنة مرصودة "
                f"(insufficient data for a trend)")
    else:
        note = (f"استيراد HS{hs_code} عبر {observed_years[0]}–{observed_years[-1]}؛ "
                f"نمو {g}% (CAGR {c}%) — {len(observed_years)}/{len(years)} "
                f"سنة مرصودة، الفجوات معلنة")
    return {
        "hs_code": str(hs_code), "market_m49": str(market_m49),
        "years": years, "series": series,
        "growth_pct": g, "cagr_pct": c,
        "observed_years": observed_years, "gap_years": gap_years,
        "source": "UN Comtrade", "retrieved_at": _today(), "note": note,
    }


_ = DataPoint  # العقد المشترك مستورد للتناظر — shared contract, imported for symmetry


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk trend engine — multi-year import trend "
          "(offline: declares gap years, never fabricates a 0)\n")
    tr = import_trend("080410", 784, 2023, span=5)  # UAE dates 2019–2023
    print(f"  {tr['note']}")
    for pt in tr["series"]:
        v = "no data" if pt["value"] is None else f"${pt['value']:,.0f}"
        print(f"    {pt['year']}: {v}")

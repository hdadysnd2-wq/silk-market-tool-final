"""محرّك اكتشاف الفرص المعكوس لسِلك — Silk reverse opportunity discovery (wave 5a).

قلب اتجاه السؤال (vision §11): بدل "عندي منتج — أين أبيعه؟" يجيب:
**"عندي سوق مستهدف — ما المنتجات المطلوبة فيه التي تمثّل فرصة لمصدّر سعودي؟"**

**صفر مصادر بيانات جديدة (§11.5-4):** يعمل حصراً على Comtrade (عبر
`silk_data_layer.comtrade_trade` القائمة) + trends (pytrends) الاختيارية —
اختبار AST بنيوي يثبت ذلك.

الإشارات المحسوبة (من §11.2):
  1. **نمو الاستيراد** — أعلى رموز HS نمواً في استيراد السوق عبر 3 سنوات.
  2. **فجوة الحصة السعودية** — منتجات يستوردها السوق بكثافة وحصة السعودية
     فيها منخفضة رغم كون السعودية مصدّراً عالمياً لها.
  3. **الموسمية القادمة** (pytrends، تكميلية بوزن أدنى — §11.4).

**حدود معلنة (§11.4):** إشارة "القرب اللوجستي" **غير محسوبة في هذه
النسخة** — تتطلب إسناد مسافات/تكاليف شحن غير موجود في مصادرنا القائمة،
واختلاقه ممنوع؛ تُعلن فجوةً في الناتج. المحرّك لا يتنبأ ("نما 40% في
3 سنوات" لا "سينمو")، ولا حشو: إن وُجدت 4 فرص فقط تُعرض 4 بصدق.
"""
from __future__ import annotations

import functools
import logging

from silk_data_layer import (DataPoint, comtrade_trade, primary_value,
                             ISO3_TO_M49, _today)

log = logging.getLogger(__name__)

_SAUDI_M49 = "682"
_DEFAULT_YEAR = 2022
_MAX_OPPORTUNITIES = 15          # §11.2: أعلى 10-15 — سقف لا هدف حشو
_GAP_SHARE_PCT = 5.0             # حصة سعودية "منخفضة" تحت هذه النسبة
_MIN_GROWTH_PCT = 15.0           # عتبة نمو ذات دلالة عبر 3 سنوات

# فصول HS للقطاعات — sector filters over HS chapters.
_SECTORS = {
    "food": {f"{n:02d}" for n in range(1, 25)},
    "textile": {f"{n:02d}" for n in range(50, 64)},
    "industrial": {f"{n:02d}" for n in range(25, 50)} |
                  {f"{n:02d}" for n in range(64, 100)},
}


@functools.lru_cache(maxsize=1)
def _hs_names() -> dict:
    """أسماء رموز HS من المرجع القائم — HS names from the existing seed CSV."""
    try:
        from silk_hs_resolver import load_hs_codes
        return {r["hs_code"]: (r.get("name_ar") or r.get("name_en") or "")
                for r in load_hs_codes()}
    except Exception as e:  # noqa: BLE001 — الاسم زينة، الرمز هو الأصل
        log.warning("HS names unavailable: %s", e)
        return {}


def _totals_by_hs(records: list[dict]) -> dict[str, float]:
    """إجمالي الاستيراد لكل رمز — total import value per HS code from records.

    سجل بلا primaryValue رقمية يُسقَط ولا يُعدّ صفراً — صفرٌ مختلق هنا يولّد
    نسبة نمو/حصة مختلقة لاحقاً (المبدأ التأسيسي). Records lacking a numeric
    value are dropped, never counted as 0 (a fabricated 0 would fabricate a
    growth rate or Saudi share downstream).
    """
    out: dict[str, float] = {}
    for rec in records or []:
        code = str(rec.get("cmdCode") or "").strip()
        if not code or code == "TOTAL":
            continue
        # بوابة النطاق غير النفطي (8d): رموز الفصول المستبعدة (وقود معدنية)
        # لا تدخل حسابات الفرص أصلاً — سِلك منصة تصدير غير نفطي.
        from silk_hs_resolver import exclusion_note
        if exclusion_note(code):
            continue
        val = primary_value(rec)
        if val is None:
            continue
        out[code] = out.get(code, 0.0) + val
    return out


def growth_signal(older: dict[str, float], newer: dict[str, float],
                  years: tuple[int, int]) -> dict[str, dict]:
    """إشارة النمو — per-HS growth % across the window (pure, testable)."""
    out: dict[str, dict] = {}
    for code, new_v in newer.items():
        old_v = older.get(code)
        if not old_v or old_v <= 0 or new_v <= 0:
            continue
        pct = round(100.0 * (new_v - old_v) / old_v, 1)
        if pct >= _MIN_GROWTH_PCT:
            out[code] = {"type": "import_growth",
                         "evidence": f"نما استيراده {pct}% بين {years[0]} "
                                     f"و{years[1]} ({old_v:,.0f}$ → {new_v:,.0f}$)",
                         "strength": pct, "source": "UN Comtrade"}
    return out


def saudi_gap_signal(market_totals: dict[str, float],
                     saudi_to_market: dict[str, float],
                     saudi_world_exports: dict[str, float],
                     year: int) -> dict[str, dict]:
    """إشارة الفجوة السعودية — high imports, low Saudi share, Saudi exports it.

    الشرط الثلاثي (§11.2): السوق يستورد الرمز بكثافة + حصة السعودية فيه
    أقل من العتبة + السعودية مصدّر عالمي فعلي له (صادراتها للعالم > 0).
    """
    out: dict[str, dict] = {}
    for code, total in market_totals.items():
        if total <= 0 or saudi_world_exports.get(code, 0.0) <= 0:
            continue
        share = 100.0 * saudi_to_market.get(code, 0.0) / total
        if share < _GAP_SHARE_PCT:
            out[code] = {"type": "saudi_share_gap",
                         "evidence": f"يستورده السوق بـ{total:,.0f}$ ({year}) "
                                     f"وحصة السعودية {share:.1f}% رغم أنها "
                                     "مصدّر عالمي له "
                                     f"({saudi_world_exports[code]:,.0f}$ للعالم)",
                         "strength": round(_GAP_SHARE_PCT - share, 1),
                         "source": "UN Comtrade"}
    return out


def _seasonality_signal(name: str, iso2: str | None) -> dict | None:
    """إشارة الموسمية (تكميلية) — pytrends peak month; None when unavailable."""
    try:
        from silk_trends_agent import _seasonality
        dp = _seasonality(name, iso2, "today 12-m")
        if dp.value is None:
            return None
        return {"type": "seasonality", "strength": 1.0,
                "evidence": f"ذروة بحث موسمية بالشهر {dp.value} — {dp.note}",
                "source": "Google Trends (تكميلية — بحث لا شراء)"}
    except Exception as e:  # noqa: BLE001 — إشارة تكميلية لا تُسقط الاكتشاف
        log.warning("seasonality signal unavailable: %s", e)
        return None


def rank_opportunities(growth: dict[str, dict], gaps: dict[str, dict],
                       market_totals: dict[str, float],
                       sector: str | None = None,
                       min_import_usd: float = 0.0) -> list[dict]:
    """رتّب الفرص — merge signals per HS and rank (pure, testable).

    الوزن: نمو + فجوة أساسيتان؛ الموسمية تُلحق لاحقاً بوزن أدنى (§11.4).
    لا حشو: رمز بلا إشارة حقيقية لا يظهر إطلاقاً (§11.5-2).
    """
    chapters = _SECTORS.get(sector or "")
    names = _hs_names()
    out: list[dict] = []
    for code in set(growth) | set(gaps):
        if chapters and code[:2] not in chapters:
            continue
        if market_totals.get(code, 0.0) < min_import_usd:
            continue
        signals = [s for s in (growth.get(code), gaps.get(code)) if s]
        if not signals:
            continue
        score = sum({"import_growth": min(s["strength"], 200) / 200,
                     "saudi_share_gap": s["strength"] / _GAP_SHARE_PCT}
                    .get(s["type"], 0.0) for s in signals)
        out.append({"hs_code": code,
                    "name": names.get(code, "") or f"HS {code}",
                    "market_import_usd": market_totals.get(code),
                    "signals": signals,
                    "signal_count": len(signals),
                    "score": round(score, 3)})
    out.sort(key=lambda o: (o["signal_count"], o["score"]), reverse=True)
    return out[:_MAX_OPPORTUNITIES]


def discover(market_iso3: str, year: int | None = None, *,
             sector: str | None = None, min_import_usd: float = 0.0,
             with_seasonality: bool = False, iso2: str | None = None) -> dict:
    """اكتشف فرص سوق — the full reverse-discovery pipeline for one market.

    4 نداءات Comtrade كحد أقصى (كلها عبر الطبقة القائمة): استيراد السوق
    AG6 لسنتين + استيراده من السعودية + صادرات السعودية للعالم. أي فشل
    جلب = فجوة معلنة في `gaps` — لا اختلاق.
    """
    year = year or _DEFAULT_YEAR
    m49 = ISO3_TO_M49.get((market_iso3 or "").upper())
    if not m49:
        return {"market": market_iso3, "opportunities": [], "gaps": [
            f"سوق غير معروف الرمز: {market_iso3}"], "preliminary": True}

    gaps: list[str] = ["إشارة القرب اللوجستي غير محسوبة في هذه النسخة — "
                       "تتطلب إسناد شحن غير متاح بمصادرنا (فجوة معلنة، §11.4)"]
    newer = _totals_by_hs(comtrade_trade("AG6", m49, year, flow="M", partner=0) or [])
    older = _totals_by_hs(comtrade_trade("AG6", m49, year - 2, flow="M",
                                         partner=0) or [])
    saudi_in = _totals_by_hs(comtrade_trade("AG6", m49, year, flow="M",
                                            partner=int(_SAUDI_M49)) or [])
    saudi_x = _totals_by_hs(comtrade_trade("AG6", int(_SAUDI_M49), year,
                                           flow="X", partner=0) or [])
    for label, data in (("استيراد السوق (السنة الأحدث)", newer),
                        ("استيراد السوق (قبل سنتين)", older),
                        ("استيراد السوق من السعودية", saudi_in),
                        ("صادرات السعودية للعالم", saudi_x)):
        if not data:
            gaps.append(f"تعذّر جلب {label} — الإشارات المعتمدة عليه ناقصة")

    growth = growth_signal(older, newer, (year - 2, year))
    gap_sig = saudi_gap_signal(newer, saudi_in, saudi_x, year)
    opportunities = rank_opportunities(growth, gap_sig, newer,
                                       sector=sector,
                                       min_import_usd=min_import_usd)
    if with_seasonality:
        for opp in opportunities:
            s = _seasonality_signal(opp["name"], iso2)
            if s:
                opp["signals"].append(s)  # تكميلية — لا تغيّر الترتيب (§11.4)

    return {
        "market": market_iso3.upper(), "m49": m49, "year": year,
        "sector": sector, "preliminary": True,
        "retrieved_at": _today(),
        "opportunities": opportunities,
        "count": len(opportunities),
        "gaps": gaps,
        "note": ("أنماط قائمة في بيانات تاريخية، لا تنبؤ (§11.4)؛ "
                 "كل إشارة قابلة للتتبع لمصدرها؛ لا حشو — العدد الصادق "
                 f"هو {len(opportunities)}. لكل فرصة مرّر hs_code إلى "
                 "التحليل الكامل مباشرة."),
    }


_ = DataPoint  # العقد المشترك مستورد للتناظر مع بقية الوحدات

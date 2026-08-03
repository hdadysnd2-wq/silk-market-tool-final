"""وكيل الاشتراطات لسِلك — Silk requirements/compliance agent (waves 3 + 5b).

القسم الخامس من الرؤية كاملاً: **الطبقة ١** مرجع ثابت في
`data/requirements_l1.csv` (خليجي + **سلسلة القرار الأوروبية** §12.2
بلوائحها المرقّمة من EUR-Lex + بنود **الخروج السعودي** §12.6) يُقرأ من
القرص بلا شبكة؛ **الطبقة ٢** بحث حي مستهدف (أسئلة تحقق محددة، لا اكتشاف
من صفر — §12.3) اختياري بمفتاح بحث؛ **الطبقة ٣** عمل قالب العرض.

تصنيف «قابلية التقنين» (§12.5) يظهر على القائمة نفسها:
  مقنّن بالكامل (الاتحاد الأوروبي/بريطانيا) > شبه موحّد (الخليج) >
  موثّق جزئياً (البقية — بنودها تحمل «تحقق محلياً» صراحةً).

«الأهلية أولاً» (§12.2-1): منتج حيواني المصدر إلى أوروبا — بند إدراج
المنشأة يتصدر القائمة والبنود التالية تُوسم مشروطةً به، لا تُسرد كأن
الطريق سالك (§12.7-2).

حدود صريحة: مرجع يُزامَن دورياً (الملاحق الأوروبية ~كل 6 أشهر) —
**ليس** استشارة قانونية؛ سوق غير مغطى = فجوة «تحقق محلياً» لا اختلاق.
"""
from __future__ import annotations

import csv
import functools
import logging
import os

import silk_blocs
from silk_data_layer import DataPoint, _today
from silk_agents import BaseAgent, AgentReport

log = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_CSV = os.path.join(_HERE, "data", "requirements_l1.csv")
_SOURCE = "Silk L1 requirements reference (official portals / EUR-Lex)"

# توسعات وسوم الأسواق — market wildcards in the reference. عضويةُ الكُتل من
# المصدر الواحد (`silk_blocs`) لا مكتوبةً صلباً هنا — DEF-2: كانت `_EU` تحمل
# ١٥ عضواً فقط فتسقط سلسلةُ الامتثال عن ١٢ دولةً عضواً بصمت. الآن EU27 كاملة.
_GCC = silk_blocs.GCC
_EU = silk_blocs.EU27

# فصول HS — food (01-24) والحيواني المصدر (§12.2-1).
_FOOD_CHAPTERS = {f"{n:02d}" for n in range(1, 25)}
_ANIMAL_CHAPTERS = {"01", "02", "03", "04", "05", "16"}

# طيف قابلية التقنين (§12.5) — الدرجة تظهر على القائمة نفسها.
_TIERS = (
    (_EU | {"GBR"}, "مقنّن بالكامل",
     "لوائح مرقّمة (EUR-Lex) — بحث حي للتغييرات فقط؛ ثقة عالية"),
    (_GCC, "شبه موحّد",
     "خريطة من مصادر رسمية، تحديث ربع سنوي؛ ثقة متوسطة-عالية"),
)
_TIER_PARTIAL = ("موثّق جزئياً",
                 "مرجع محدود + اعتماد أكبر على البحث الحي — "
                 "البنود غير المؤكدة موسومة «تحقق محلياً»")


def codification_tier(market: str) -> tuple[str, str]:
    """درجة قابلية التقنين — the market's codification tier (§12.5)."""
    for markets, tier, note in _TIERS:
        if market in markets:
            return tier, note
    return _TIER_PARTIAL


def hs_category(hs_code: str | None) -> str:
    """صنّف فئة المرجع من رمز HS — 'food' for chapters 01-24, else 'all'."""
    digits = "".join(ch for ch in str(hs_code or "") if ch.isdigit())
    return "food" if digits[:2] in _FOOD_CHAPTERS else "all"


def is_animal_origin(hs_code: str | None) -> bool:
    """حيواني المصدر؟ — HS chapters 01-05 & 16 (vision §12.2-1)."""
    digits = "".join(ch for ch in str(hs_code or "") if ch.isdigit())
    return digits[:2] in _ANIMAL_CHAPTERS


@functools.lru_cache(maxsize=1)
def _load_reference() -> tuple[dict, ...]:
    """حمّل مرجع الطبقة ١ — read the L1 CSV once (offline, no network)."""
    try:
        with open(_CSV, newline="", encoding="utf-8") as f:
            return tuple(csv.DictReader(f))
    except Exception as exc:  # noqa: BLE001 — missing reference degrades, never crashes
        log.warning("L1 requirements reference unavailable (%s): %s", _CSV, exc)
        return ()


def _matches(row: dict, market: str, category: str, direction: str,
             animal: bool) -> bool:
    """هل ينطبق البند؟ — row applies to market×category×direction?"""
    row_market = (row.get("market") or "").strip().upper()
    market_ok = (row_market == market
                 or (row_market == "GCC" and market in _GCC)
                 or (row_market == "EU" and market in _EU))
    row_cat = (row.get("category") or "all").strip().lower()
    cat_ok = (row_cat == "all" or row_cat == category
              or (row_cat == "animal" and animal))
    dir_ok = (row.get("direction") or "").strip().lower() == direction
    return market_ok and cat_ok and dir_ok


def _seq(row: dict) -> int:
    """ترتيب سلسلة القرار — the row's decision-chain order (default 50)."""
    try:
        return int(row.get("seq") or 50)
    except ValueError:
        return 50


def _row_dp(row: dict, direction: str, conditional: bool = False) -> DataPoint:
    """بند مرجع كنقطة موسومة — one checklist item as a provenance DataPoint."""
    try:
        conf = float(row.get("confidence") or 0.5)
    except ValueError:
        conf = 0.5
    note = row.get("note") or "مرجع طبقة ١ — تحقق قبل الشحن"
    if conditional:
        note += " | مشروط باجتياز بند الأهلية أعلاه — لا تعتبره سالكاً قبله"
    return DataPoint(
        value={"item": row.get("item_ar"), "authority": row.get("authority"),
               "direction": direction, "source_url": row.get("source_url"),
               "seq": _seq(row)},
        source=_SOURCE, confidence=conf, note=note, retrieved_at=_today())


def _live_verification(items: list[DataPoint], market: str) -> list[DataPoint]:
    """الطبقة ٢ — بحث حي بأسئلة تحقق محددة (§12.3)، لا اكتشاف من صفر.

    اختيارية بمفتاح بحث؛ keyless/بلا شبكة => نقطة فجوة موسومة واحدة.
    سؤال واحد مستهدف (أعلى بند بالسلسلة) — لا استعلامات عامة.
    """
    try:
        from silk_websearch_agent import web_search
        top = next((dp for dp in items if dp.value), None)
        if top is None:
            return []
        authority = str(top.value.get("authority") or "")
        query = (f"latest amendment revision {authority} import requirements "
                 f"{market}")
        raw = web_search(query, num=2)
        real = [f for f in raw if f.value is not None]
        if not real:
            note = raw[0].note if raw else "no results"
            return [DataPoint(None, "Live verification (Serper)", 0.0,
                              f"التحقق الحي غير متاح ({note}) — اعتمد على "
                              "مرجع الطبقة ١ وتاريخ مزامنته", _today())]
        return [DataPoint(f.value, "Live verification (Serper)", 0.4,
                          f"تحقق حي مستهدف: '{query}' — نتيجة غير مُتحقَّقة، "
                          "قارنها بالنص الرسمي", _today()) for f in real]
    except Exception as e:  # noqa: BLE001 — الطبقة ٢ لا تُسقط الطبقة ١
        log.warning("live verification failed for %s: %s", market, e)
        return [DataPoint(None, "Live verification (Serper)", 0.0,
                          f"التحقق الحي فشل: {type(e).__name__}", _today())]


class RequirementsAgent(BaseAgent):
    """وكيل الاشتراطات — dual-direction compliance checklist (L1 + L2)."""

    PAID = False
    PREF_KEY = "regulatory"
    SOURCE = _SOURCE

    def __init__(self) -> None:
        super().__init__("RequirementsAgent")

    def _execute(self, task: dict) -> AgentReport:
        """قائمة تحقق الدخول+الخروج — entry (market) + Saudi-exit checklist.

        task keys: market_iso3, hs_code, category (اختياري)،
        with_live_verification (اختياري — الطبقة ٢). Fully offline by default.
        """
        market = (task.get("market_iso3") or task.get("iso3") or "").strip().upper()
        if not market:
            return AgentReport(self.name, [], True,
                               "لا سوق — missing market_iso3")
        hs = task.get("hs_code")
        category = (task.get("category") or hs_category(hs)).lower()
        animal = is_animal_origin(hs)
        rows = _load_reference()
        if not rows:
            return AgentReport(
                self.name,
                [DataPoint(None, _SOURCE, 0.0,
                           "مرجع الطبقة ١ غير متاح — L1 reference unavailable",
                           _today())],
                True, "لا مرجع اشتراطات — L1 reference unavailable")

        tier, tier_note = codification_tier(market)
        entry_rows = sorted((r for r in rows
                             if _matches(r, market, category, "entry", animal)),
                            key=_seq)
        # الأهلية أولاً (§12.7-2): وجود بند حيواني seq=10 يجعل البقية مشروطة.
        eligibility_first = (animal and entry_rows
                             and (entry_rows[0].get("category") or "") == "animal")
        entry = [_row_dp(r, "entry",
                         conditional=(eligibility_first and i > 0))
                 for i, r in enumerate(entry_rows)]
        exit_items = [_row_dp(r, "exit")
                      for r in sorted((r for r in rows
                                       if _matches(r, "SAU", category,
                                                   "exit", animal)), key=_seq)]

        findings: list[DataPoint] = []
        if entry:
            findings.extend(entry)
        else:
            findings.append(DataPoint(
                None, _SOURCE, 0.0,
                f"سوق {market} ({tier}) غير مغطى بالمرجع الثابت بعد — "
                "تحقق محلياً (verify locally)", _today()))
        findings.extend(exit_items)

        if task.get("with_live_verification"):
            findings.extend(_live_verification(entry, market))

        summary = (f"[{tier}] "
                   + (f"{len(entry)} entry item(s) for {market} ({category}"
                      f"{', animal-origin' if animal else ''}) "
                      if entry else
                      f"سوق {market} بلا مرجع دخول (تحقق محلياً) ")
                   + f"+ {len(exit_items)} Saudi-exit item(s)"
                   + (" | الأهلية أولاً: البنود التالية مشروطة بها"
                      if eligibility_first else ""))
        return AgentReport(self.name, findings, False, summary)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk RequirementsAgent — L1 (GCC + EU chain) + optional L2, offline")
    for market, hs in (("ARE", "080410"), ("DEU", "080410"),
                       ("DEU", "040900"), ("KEN", "080410")):
        rep = RequirementsAgent().run({"market_iso3": market, "hs_code": hs})
        print(f"  [{market} × {hs}] {rep.summary}")

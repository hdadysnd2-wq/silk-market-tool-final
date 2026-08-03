"""اختبار رجعي لمحرك القرار — Stage 4 backtest for GATE 3 (خيار الأوزان A/B).

يعيد تشغيل حالات تصدير سعودية تاريخية موثّقة النتيجة (data/backtest_cases.csv)
عبر وكلاء البحث الحقيقيين + محرك القرار، ويقيس اتفاق كل خيار أوزان مع النتيجة
الموثّقة. **الدليل الصالح للبوابة هو التشغيل الحي على النشر** (مخزن حقائق
مُدفّأ بـ tools/refresh.py + مفاتيح الخادم) — الوضع --demo يبرهن الميكانيكا
فقط ببدائل موسومة ولا يصلح دليلاً.

قاعدة الاتفاق (معلنة، متحفظة):
  success ⇒ يتفق القرار إذا لم يكن NO-GO (دخول متحقق تاريخياً لا يُرفض).
  stalled ⇒ يتفق القرار إذا لم يكن GO صريحاً (تعثر تاريخي لا يُوصى به بلا شرط).

Usage:  python3 tools/backtest.py [--demo]        # الافتراضي: المخزن/الشبكة الحية
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)

_CASES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "data", "backtest_cases.csv")


def load_cases() -> list[dict]:
    with open(_CASES, encoding="utf-8") as fh:
        rows = [r for r in fh if not r.startswith("#")]
    return list(csv.DictReader(rows))


def agrees(outcome: str, verdict: str) -> bool:
    """قاعدة الاتفاق المعلنة — success ⇒ ليس NO-GO؛ stalled ⇒ ليس GO."""
    if outcome == "success":
        return verdict != "NO-GO"
    return verdict != "GO"


def _seed_demo_store(case: dict) -> None:
    """بدائل demo موسومة — ميكانيكا فقط، ليست دليلاً (تُطبع بهذا الوسم)."""
    import silk_store
    silk_store.migrate()
    flows = {
        "success": [("WLD", 2.0e8, 6.0e7), ("SAU", 5.0e7, 1.6e7),
                    ("OTH", 9.0e7, 3.0e7)],
        "stalled": [("WLD", 2.9e8, 5.0e7), ("UKR", 6.0e7, 1.2e7),
                    ("MEX", 4.4e7, 9.0e6)],
    }[case["outcome"]]
    silk_store.upsert_trade_flows([
        {"hs6": case["hs6"], "reporter_iso3": case["iso3"], "partner_iso3": p,
         "year": int(case["year"]), "flow": "M", "value_usd": v, "qty_kg": q,
         "source": "demo double (ليست بيانات)"} for p, v, q in flows])
    for ind, v in (("NY.GDP.PCAP.CD", 20_000), ("PV.EST", 0.2), ("RQ.EST", 0.4),
                   ("LP.LPI.OVRL.XQ", 3.5)):
        silk_store.upsert_indicator(case["iso3"], ind, int(case["year"]), v,
                                    "demo double (ليست بيانات)", 0.5)


def run(demo: bool = False) -> dict:
    import silk_decision
    from silk_research import ResearchOrchestrator
    out = {"mode": "demo (ميكانيكا فقط — ليس دليل بوابة)" if demo else "live",
           "cases": [], "agreement": {}}
    orch = ResearchOrchestrator()
    for case in load_cases():
        if demo:
            import tempfile
            os.environ["SILK_HERMETIC"] = "1"   # وسم TEST RUN — ليس دليلاً
            os.environ["SILK_STORE_DB"] = os.path.join(tempfile.mkdtemp(), "b.db")
            _seed_demo_store(case)
        bundle = orch.run_market({
            "product": case["product"], "hs6": case["hs6"],
            "iso3": case["iso3"], "m49": case["m49"], "iso2": case["iso2"],
            "market_name": case["market_name"], "year": int(case["year"])})
        row = {"case": case["case_id"], "documented_outcome": case["outcome"],
               "evidence": case["evidence"], "coverage": bundle["coverage"]}
        for optname in ("A", "B"):
            d = silk_decision.decide(bundle, weights_option=optname)
            row[optname] = {"verdict": d["verdict"], "score": d["score"],
                            "confidence": d["confidence"],
                            "agrees": agrees(case["outcome"], d["verdict"])}
        out["cases"].append(row)
    for optname in ("A", "B"):
        hits = sum(1 for c in out["cases"] if c[optname]["agrees"])
        out["agreement"][optname] = f"{hits}/{len(out['cases'])}"
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="بدائل موسومة لبرهنة الميكانيكا فقط — ليست دليلاً")
    args = ap.parse_args()
    print(json.dumps(run(demo=args.demo), ensure_ascii=False, indent=1))

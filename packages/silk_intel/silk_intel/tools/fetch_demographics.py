#!/usr/bin/env python3
"""جالب مرجع الديموغرافيا العالمي — build data/demographics_l1.csv.

يمدّد (لا يُكرّر) مرجعين موجودين بدل إعادة بنائهما من الصفر:
  - `data/muslim_share.csv` — بذرة سِلك المنسَّقة (٤٩ سوقاً، Pew Research،
    قيَم دقيقة مراجَعة يدوياً) — تبقى الأولوية العليا حيث تغطي.
  - `data/worldbank_seed.csv` — سكان شبه عالمي (٢١٥/٢٥٠ دولة).
ويوسّع تغطية نسبة السكان المسلمين عبر مصدر Pew **نفسه** بشكل مهيكل:
مجموعة بيانات datasets/world-religion-projections (Pew Research —
The Future of World Religions، ٢٠١٠-٢٠٥٠، ترخيص CC BY 4.0) — ٢٣٤ دولة لسنة
٢٠٢٠. صفوف قيمتها "1.0" في تلك المجموعة قيمة **مقصوصة** (Pew توثّق: أي حصة
دون 1% تُعرض 1.0) — تُعلَّم صراحةً «≤1% (مقصوصة)» بدل عرضها رقماً دقيقاً.

سوق بلا سكان و/أو بلا نسبة مسلمين موثّقة = فجوة معلنة (حقل فارغ + ملاحظة)،
لا اختلاق (المبدأ التأسيسي).

NETWORK REQUIRED / يتطلب إنترنت لجلب مجموعة بيانات Pew؛ عند الفشل يطبع
رسالة واضحة ويخرج بكود غير صفري — لا يكتب صفوفاً مختلقة.

Usage:
    python3 tools/fetch_demographics.py [--path data/demographics_l1.csv]
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys

log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RELIGION_URL = ("https://raw.githubusercontent.com/datasets/"
                 "world-religion-projections/main/rounded_percentage.csv")
_RELIGION_SOURCE = ("Pew Research Center — The Future of World Religions "
                    "(via datasets/world-religion-projections, CC BY 4.0)")
_RELIGION_SOURCE_URL = ("https://github.com/datasets/world-religion-projections"
                        " — original: https://www.pewresearch.org/religion/"
                        "feature/religious-composition-by-country-2010-2050/")
_PEW_YEAR = "2020"

FIELDNAMES = ["iso3", "name_en", "population", "population_year",
             "population_source", "muslim_pct", "muslim_pct_year",
             "muslim_pct_source", "note"]


def _fetch_religion_rows() -> list[dict]:
    import requests  # lazy: keep module importable offline
    resp = requests.get(_RELIGION_URL, timeout=30)
    resp.raise_for_status()
    text = resp.text
    reader = csv.DictReader(text.splitlines())
    return [{k.strip(): (v or "").strip() for k, v in row.items()}
           for row in reader if row.get("Year", "").strip() == _PEW_YEAR]


def build(path: str = "data/countries.csv",
         muslim_seed: str = "data/muslim_share.csv",
         wb_seed: str = "data/worldbank_seed.csv") -> list[dict]:
    from silk_market_resolver import resolve_market

    def _rows(fp: str) -> list[dict]:
        # بعض المراجع (muslim_share.csv) تسبق رأسها بأسطر تعليق "#" توثّق
        # المصدر — تُستثنى قبل DictReader فلا يظنّها الرأس. Skip leading
        # '#' comment lines (source documentation) before the real header.
        with open(fp, encoding="utf-8") as f:
            lines = [ln for ln in f if not ln.startswith("#")]
        return list(csv.DictReader(lines))

    countries = _rows(os.path.join(_HERE, path))
    seed_muslim = {r["iso3"]: r for r in _rows(os.path.join(_HERE, muslim_seed))}
    wb = {r["iso3"]: r for r in _rows(os.path.join(_HERE, wb_seed))}

    religion_rows = _fetch_religion_rows()
    # اسم الدولة (Pew) -> iso3 عبر مُحلِّل السوق (نفس المطابقة الدقيقة+التقريبية
    # المستعملة للمدخل البشري — إعادة استعمال لا منطق مطابقة موازٍ).
    pew_by_iso3: dict[str, dict] = {}
    unmatched: list[str] = []
    for row in religion_rows:
        name = row.get("Country", "").strip()
        if not name:
            continue
        ref, _sugg = resolve_market(name, path=os.path.join(_HERE, path))
        if ref is None:
            unmatched.append(name)
            continue
        pew_by_iso3[ref.iso3] = row

    rows: list[dict] = []
    for c in countries:
        iso3 = c["iso3"]
        wb_row = wb.get(iso3)
        pop = (wb_row or {}).get("population") or ""
        pop_year = (wb_row or {}).get("pop_year") or ""
        pop_source = "World Bank (data/worldbank_seed.csv)" if pop else ""

        seed = seed_muslim.get(iso3)
        if seed:  # الأولوية للبذرة المنسَّقة يدوياً — precise, already reviewed
            muslim_pct = seed.get("muslim_share_pct", "")
            muslim_year = seed.get("ref_year", "")
            muslim_source = ("Pew Research (Silk curated seed — "
                             "data/muslim_share.csv)")
            note = seed.get("note", "")
        else:
            pew = pew_by_iso3.get(iso3)
            if pew:
                val = pew.get("Muslims", "")
                muslim_pct = val
                muslim_year = _PEW_YEAR
                muslim_source = _RELIGION_SOURCE
                note = ("≤1% (مقصوصة عند 1.0 في مصدر Pew المهيكل — القيمة "
                        "الحقيقية قد تكون أدنى) — clamped at 1.0 by Pew's "
                        "own dataset documentation" if val == "1.0" else "")
            else:
                muslim_pct = muslim_year = muslim_source = ""
                note = "لا نسبة مسلمين موثّقة لهذا السوق — فجوة معلنة"

        if not pop:
            note = (note + "؛ " if note else "") + "لا عدد سكان في المرجع الحالي"

        rows.append({
            "iso3": iso3, "name_en": c.get("name_en", ""),
            "population": pop, "population_year": pop_year,
            "population_source": pop_source,
            "muslim_pct": muslim_pct, "muslim_pct_year": muslim_year,
            "muslim_pct_source": muslim_source, "note": note.strip("؛ "),
        })

    if unmatched:
        log.warning("Pew country names unmatched to an iso3 (%d, sample): %s",
                   len(unmatched), unmatched[:10])
    return rows


def write_csv(rows: list[dict], path: str) -> None:
    fp = path if os.path.isabs(path) else os.path.join(_HERE, path)
    header = (
        "# مرجع الديموغرافيا L1 — سكان (World Bank) + نسبة مسلمين (Pew "
        "Research). يُبنى عبر tools/fetch_demographics.py — لا يُعدَّل يدوياً.\n"
        f"# Muslim %% source: {_RELIGION_SOURCE_URL}\n")
    with open(fp, "w", newline="", encoding="utf-8") as f:
        f.write(header)
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default="data/demographics_l1.csv")
    args = ap.parse_args()
    try:
        rows = build()
    except Exception as e:  # noqa: BLE001 — clear failure, never fabricate
        log.error("build failed: %s: %s", type(e).__name__, e)
        return 1
    if not rows:
        log.error("zero rows built — refusing to write an empty reference")
        return 1
    write_csv(rows, args.path)
    with_pop = sum(1 for r in rows if r["population"])
    with_muslim = sum(1 for r in rows if r["muslim_pct"])
    log.info("wrote %d countries to %s (population: %d, muslim_pct: %d)",
             len(rows), args.path, with_pop, with_muslim)
    return 0


if __name__ == "__main__":
    sys.exit(main())

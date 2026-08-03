#!/usr/bin/env python3
"""جالب مرجع الاتفاقيات التجارية — build data/agreements_l1.csv.

عضوية التكتلات (GCC/GAFTA/OIC/AfCFTA/WTO) حقيقة تصنيفية مستقرة وموثَّقة
علنياً — لا رقم إحصائي يحتاج جلباً حياً، فتُدرَج هنا كجدول منسَّق (نفس
نمط `data/requirements_l1.csv`: كل صف يستشهد بمصدره الرسمي).

**نطاق هذه الموجة (١) صراحةً**: تغطية كاملة موثوقة لأسواق سِلك الـ٣٨
المستهدفة (`silk_market_ranker.COUNTRIES`) فقط — لا الـ٢٥٠ دولة عالمياً.
عضوية WTO/OIC لبقية العالم تحتاج تعداداً دقيقاً (١٦٤+/٥٧ عضواً) يتجاوز ما
يمكن تثبيته بثقة في موجة واحدة دون شبكة موثوقة لكل صف — فجوة **معلنة**،
لا اختلاق (المبدأ التأسيسي)؛ سوق غير مدرَج هنا = «تحقق محلياً» عبر
`lookup_reference` (نفس رسالة الفجوة في requirements_l1).

حالات خاصة تحقّقت يدوياً (لا افتراض تلقائي «عضو» لكل سوق قريب جغرافياً):
لبنان والجزائر وإثيوبيا **ليست** أعضاء WTO كاملة العضوية (لبنان/الجزائر
في مسار انضمام منذ عقود؛ إثيوبيا كذلك منذ ٢٠٠٣) — تُوسم صراحةً
"in_accession" لا "member".

لا نداء شبكي هنا (بيانات ثابتة مُدخلة يدوياً بمصادرها) — السكربت يكتب
المرجع مباشرة؛ الاسم يطابق نمط tools/fetch_*.py الأخرى لغرض الاتساق فقط.

Usage:
    python3 tools/fetch_agreements.py [--path data/agreements_l1.csv]
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys

log = logging.getLogger(__name__)
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SRC = {
    "GCC": ("مجلس التعاون لدول الخليج العربية — اتحاد جمركي (تعرفة موحدة "
           "5% تجاه الخارج، إعفاء كامل بين الأعضاء)", "https://gcc-sg.org"),
    "GAFTA": ("منطقة التجارة الحرة العربية الكبرى — جامعة الدول العربية "
             "(إعفاء جمركي شبه كامل على غالب السلع عربية المنشأ)",
             "https://www.lasportal.org"),
    "OIC": ("منظمة التعاون الإسلامي — عضوية تعاون، لا اتحاد جمركي مباشر؛ "
           "نظام التفضيلات التجارية OIC-TPS تصديقه جزئي بين الأعضاء "
           "(يتطلب تحقق حي لكل دولة)", "https://www.oic-oci.org"),
    "AfCFTA": ("منطقة التجارة الحرة القارية الأفريقية — تخفيض تعريفي "
              "تدريجي (يستهدف 90% من بنود التعرفة) بحسب جدول كل دولة؛ "
              "التنفيذ الفعلي يتفاوت — تحقق من مرحلة الدولة",
              "https://au-afcftahub.au.int"),
    "WTO": ("منظمة التجارة العالمية — التزام بمبدأ الدولة الأولى بالرعاية "
           "(MFN)؛ لا تفضيل ثنائي إلا ضمن اتفاقية أخرى",
           "https://www.wto.org/english/thewto_e/whatis_e/tif_e/org6_e.htm"),
    "GCC-Singapore FTA": ("اتفاقية التجارة الحرة الخليجية-السنغافورية "
                          "(٢٠١٣) — إعفاءات جمركية على بنود محددة، تحقق "
                          "من الجدول الزمني للسلعة",
                          "https://gcc-sg.org"),
}

# سوق -> [(اتفاقية, الحالة), ...]. status: member | in_accession.
_MEMBERSHIPS: dict[str, list[tuple[str, str]]] = {
    "ARE": [("GCC", "member"), ("GAFTA", "member"), ("OIC", "member"), ("WTO", "member")],
    "QAT": [("GCC", "member"), ("GAFTA", "member"), ("OIC", "member"), ("WTO", "member")],
    "KWT": [("GCC", "member"), ("GAFTA", "member"), ("OIC", "member"), ("WTO", "member")],
    "OMN": [("GCC", "member"), ("GAFTA", "member"), ("OIC", "member"), ("WTO", "member")],
    "BHR": [("GCC", "member"), ("GAFTA", "member"), ("OIC", "member"), ("WTO", "member")],
    "JOR": [("GAFTA", "member"), ("OIC", "member"), ("WTO", "member")],
    "LBN": [("GAFTA", "member"), ("OIC", "member"), ("WTO", "in_accession")],
    "EGY": [("GAFTA", "member"), ("OIC", "member"), ("WTO", "member"), ("AfCFTA", "member")],
    "MAR": [("GAFTA", "member"), ("OIC", "member"), ("WTO", "member"), ("AfCFTA", "member")],
    "TUN": [("GAFTA", "member"), ("OIC", "member"), ("WTO", "member"), ("AfCFTA", "member")],
    "DZA": [("GAFTA", "member"), ("OIC", "member"), ("WTO", "in_accession"), ("AfCFTA", "member")],
    "IRQ": [("GAFTA", "member"), ("OIC", "member"), ("WTO", "member")],
    "TUR": [("OIC", "member"), ("WTO", "member")],
    "YEM": [("GAFTA", "member"), ("OIC", "member"), ("WTO", "member")],
    "ZAF": [("WTO", "member"), ("AfCFTA", "member")],
    "NGA": [("OIC", "member"), ("WTO", "member"), ("AfCFTA", "member")],
    "KEN": [("WTO", "member"), ("AfCFTA", "member")],
    "ETH": [("WTO", "in_accession"), ("AfCFTA", "member")],
    "GHA": [("WTO", "member"), ("AfCFTA", "member")],
    "IND": [("WTO", "member")],
    "PAK": [("OIC", "member"), ("WTO", "member")],
    "BGD": [("OIC", "member"), ("WTO", "member")],
    "IDN": [("OIC", "member"), ("WTO", "member")],
    "MYS": [("OIC", "member"), ("WTO", "member")],
    "SGP": [("WTO", "member"), ("GCC-Singapore FTA", "member")],
    "THA": [("WTO", "member")],
    "VNM": [("WTO", "member")],
    "CHN": [("WTO", "member")],
    "JPN": [("WTO", "member")],
    "KOR": [("WTO", "member")],
    "GBR": [("WTO", "member")],
    "DEU": [("WTO", "member")],
    "FRA": [("WTO", "member")],
    "ITA": [("WTO", "member")],
    "ESP": [("WTO", "member")],
    "NLD": [("WTO", "member")],
    "USA": [("WTO", "member")],
    "CAN": [("WTO", "member")],
}

FIELDNAMES = ["iso3", "name_en", "agreement", "status", "tariff_effect",
             "confidence", "source", "source_url"]


def build() -> list[dict]:
    from silk_market_resolver import resolve_market

    rows: list[dict] = []
    for iso3, memberships in _MEMBERSHIPS.items():
        ref, _sugg = resolve_market(iso3)
        if ref is None:
            log.warning("iso3 %r not found in countries.csv — skipped", iso3)
            continue
        for agreement, status in memberships:
            note, url = _SRC[agreement]
            rows.append({
                "iso3": iso3, "name_en": ref.name_en, "agreement": agreement,
                "status": status, "tariff_effect": note,
                "confidence": 0.6 if status == "in_accession" else 0.75,
                "source": f"{agreement} secretariat", "source_url": url,
            })
    return rows


def write_csv(rows: list[dict], path: str) -> None:
    fp = path if os.path.isabs(path) else os.path.join(_HERE, path)
    header = (
        "# مرجع الاتفاقيات التجارية L1 — نطاق الموجة ١: أسواق سِلك الـ٣٨ "
        "المستهدفة فقط (silk_market_ranker.COUNTRIES). Priority-market "
        "scope, not worldwide — see tools/fetch_agreements.py docstring.\n")
    rows = sorted(rows, key=lambda r: (r["iso3"], r["agreement"]))
    with open(fp, "w", newline="", encoding="utf-8") as f:
        f.write(header)
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default="data/agreements_l1.csv")
    args = ap.parse_args()
    sys.path.insert(0, _HERE)
    rows = build()
    if not rows:
        log.error("zero rows built — refusing to write an empty reference")
        return 1
    write_csv(rows, args.path)
    log.info("wrote %d rows to %s (%d markets)", len(rows), args.path,
             len({r['iso3'] for r in rows}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

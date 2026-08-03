#!/usr/bin/env python3
"""جالب مرجع الموانئ العالمي — build data/ports_l1.csv.

المصدر الساحلي: mirror لدليل الموانئ العالمي الرسمي (World Port Index —
NGA Publication 150, 2019 edition، عام المجال — public domain) عبر
tayljordan/ports (٥,٤١٠ ميناء). لكل دولة ساحلية يُختار الميناء الأعلى
تصنيف حجم (`port_size`: Major > Minor > Small > Very Small) كـ"الميناء
الرئيسي" — تعادل يُحسم بعدد حقول العمق غير الفارغة (مؤشر أهمية تشغيلية).

الدول الحبيسة (بلا ميناء في الدليل): تُدرَج **يدوياً** بممرّها اللوجستي
المعتاد — حقيقة جغرافية مستقرة وموثّقة (ميناء أثيوبيا جيبوتي، تشاد
دوالا...)، لا إحصاء يحتاج استشهاداً برقم؛ الملاحظة تصرّح أنها معلومة عامة
لا شروط تعاقدية حية (تحقق قبل الشحن).

دولة لا تظهر في الدليل الساحلي ولا في قائمة الحبيسة اليدوية = **فجوة
معلنة** (لا صف لها) — لا اختلاق (المبدأ التأسيسي).

NETWORK REQUIRED / يتطلب إنترنت لجلب دليل الموانئ؛ عند الفشل يطبع رسالة
واضحة ويخرج بكود غير صفري.

Usage:
    python3 tools/fetch_ports.py [--path data/ports_l1.csv]
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

_PORTS_URL = "https://raw.githubusercontent.com/tayljordan/ports/main/ports.json"
_SEA_SOURCE = ("World Port Index — NGA Publication 150, 2019 ed. (public "
              "domain), via github.com/tayljordan/ports")
_SEA_SOURCE_URL = "https://github.com/tayljordan/ports"
_SIZE_RANK = {"major": 4, "minor": 3, "small": 2, "very small": 1}

# ممرّات العبور المعتادة للدول الحبيسة — اسم (لمطابقة resolve_market) +
# ميناء العبور الرئيسي/البديل. حقيقة جغرافية-لوجستية عامة مستقرة، لا رقم
# إحصائي — تُوسم كذلك صراحةً في الملاحظة (لا شروط عبور تعاقدية حية).
_LANDLOCKED_CORRIDORS: dict[str, str] = {
    "Afghanistan": "ميناء كراتشي (باكستان) أو تشابهار (إيران)",
    "Armenia": "موانئ بوتي/باتومي (جورجيا)",
    "Austria": "ميناء تريستا (إيطاليا) أو روتردام (هولندا) عبر الراين",
    "Azerbaijan": "موانئ بوتي/باتومي (جورجيا) أو بحر قزوين",
    "Belarus": "موانئ بحر البلطيق (كلايبيدا، ليتوانيا)",
    "Bhutan": "ميناء كولكاتا/هالديا (الهند)",
    "Bolivia": "ميناء أريكا/أنتوفاغاستا (تشيلي) أو إيلو (بيرو)",
    "Botswana": "ميناء ديربان (جنوب أفريقيا) أو والفيس باي (ناميبيا)",
    "Burkina Faso": "ميناء أبيدجان (كوت ديفوار) أو لومي (توغو) أو تيما (غانا)",
    "Burundi": "ميناء دار السلام (تنزانيا)",
    "Central African Republic": "ميناء دوالا (الكاميرون)",
    "Chad": "ميناء دوالا (الكاميرون)",
    "Czechia": "ميناء هامبورغ (ألمانيا) أو غدانسك (بولندا)",
    "Eswatini": "ميناء ديربان (جنوب أفريقيا) أو مابوتو (موزمبيق)",
    "Ethiopia": "ميناء جيبوتي (جيبوتي) — الممرّ الرئيسي شبه الحصري",
    "Hungary": "ميناء رييكا (كرواتيا) أو هامبورغ عبر نهر الدانوب",
    "Kazakhstan": "ميناء أكتاو (بحر قزوين) أو موانئ الصين/روسيا",
    "Kyrgyzstan": "عبر كازاخستان أو الصين",
    "Laos": "ميناء دا نانغ (فيتنام) أو موانئ تايلاند",
    "Lesotho": "ميناء ديربان (جنوب أفريقيا)",
    "Liechtenstein": "عبر سويسرا إلى روتردام",
    "Luxembourg": "ميناء أنتويرب (بلجيكا) أو روتردام (هولندا)",
    "Malawi": "ميناء بيرا/ناكالا (موزمبيق) أو دار السلام (تنزانيا)",
    "Mali": "ميناء داكار (السنغال) أو أبيدجان (كوت ديفوار)",
    "Moldova": "ميناء كونستانتسا (رومانيا) أو أوديسا (أوكرانيا)",
    "Mongolia": "ميناء تيانجين (الصين) أو موانئ روسيا",
    "Nepal": "ميناء كولكاتا (الهند)",
    "Niger": "ميناء كوتونو (بنين) أو لاغوس (نيجيريا)",
    "North Macedonia": "ميناء سالونيك (اليونان)",
    "Paraguay": "عبر النهر إلى بوينس آيرس (الأرجنتين) أو مونتيفيديو (الأوروغواي)",
    "Rwanda": "ميناء دار السلام (تنزانيا) أو مومباسا (كينيا)",
    "San Marino": "موانئ إيطاليا",
    "Serbia": "ميناء بار (الجبل الأسود) أو رييكا (كرواتيا) عبر الدانوب",
    "Slovakia": "عبر بولندا/ألمانيا — نهر الدانوب",
    "South Sudan": "ميناء مومباسا (كينيا)",
    "Switzerland": "ميناء روتردام (هولندا) عبر نهر الراين",
    "Tajikistan": "عبر أوزبكستان/كازاخستان",
    "Turkmenistan": "ميناء تركمن باشي (بحر قزوين)",
    "Uganda": "ميناء مومباسا (كينيا)",
    "Uzbekistan": "عبر كازاخستان (أكتاو) أو إيران",
    "Zambia": "ميناء دار السلام (تنزانيا) أو ديربان (جنوب أفريقيا)",
    "Zimbabwe": "ميناء بيرا (موزمبيق) أو ديربان (جنوب أفريقيا)",
    "Andorra": "موانئ إسبانيا/فرنسا",
}

# تصحيح يدوي لأسواق سِلك الـ٣٨ ذات الأولوية — الاختيار الآلي (أعلى تصنيف
# حجم NGA + تعادل بعدّ حقول العمق) يصيب غالباً لكنه أخطأ لموانئ بارزة
# (اختار مرافئ نفطية/متخصصة أو موانئ ثانوية على الميناء التجاري الفعلي
# الأكبر — روتردام لا أمستردام لهولندا، شنغهاي لا داليان للصين...). هذا
# تصحيح جودة بمعرفة عامة موثّقة عن الأهمية التجارية النسبية (لا رقم
# إحصائي يحتاج استشهاداً)، مطبَّق فقط على قائمة أسواق سِلك المستهدفة
# (`silk_market_ranker.COUNTRIES`) — بقية العالم يبقى على اختيار الدليل
# الآلي كما هو. Manual quality fix for Silk's priority markets only.
PRIORITY_PORT_OVERRIDES: dict[str, str] = {
    "QAT": "Hamad Port",
    "BHR": "Khalifa Bin Salman Port (Hidd)",
    "DZA": "Algiers",
    "YEM": "Aden",
    "ZAF": "Durban",
    "GHA": "Tema",
    "IND": "Jawaharlal Nehru Port (Nhava Sheva, Mumbai)",
    "IDN": "Tanjung Priok (Jakarta)",
    "SGP": "Port of Singapore",
    "THA": "Laem Chabang",
    "CHN": "Shanghai",
    "JPN": "Yokohama",
    "GBR": "Felixstowe",
    "DEU": "Hamburg",
    "FRA": "Marseille-Fos",
    "ITA": "Genoa",
    "ESP": "Valencia",
    "NLD": "Rotterdam",
    "USA": "Los Angeles / Long Beach",
    "CAN": "Vancouver",
}
_OVERRIDE_NOTE = ("أكبر ميناء تجاري/بالحاويات فعلياً — تصحيح جودة بمعرفة "
                  "عامة موثّقة عن الأهمية التجارية النسبية، إذ اختار "
                  "التصنيف الآلي (حجم NGA + تعادل بعدّ حقول العمق) مرفأً "
                  "متخصصاً/ثانوياً لهذا السوق")

FIELDNAMES = ["iso3", "name_en", "main_port", "port_type", "logistics_note",
             "source", "source_url"]


def _fetch_ports() -> list[dict]:
    import requests  # lazy: keep module importable offline
    resp = requests.get(_PORTS_URL, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    ports = payload.get("ports") if isinstance(payload, dict) else payload
    if not ports:
        raise ValueError("unexpected payload shape (expected a 'ports' list)")
    return ports


def _depth_field_count(port: dict) -> int:
    keys = ("channel_depth_max_m", "anchorage_depth_max_m",
           "cargo_pier_depth_max_m", "oil_terminal_depth_max_m")
    return sum(1 for k in keys if port.get(k) is not None)


def build() -> list[dict]:
    from silk_market_resolver import resolve_market

    ports = _fetch_ports()
    by_iso3: dict[str, dict] = {}
    unmatched: set[str] = set()
    for p in ports:
        country = (p.get("country") or "").strip()
        if not country:
            continue
        ref, _sugg = resolve_market(country)
        if ref is None:
            unmatched.add(country)
            continue
        rank = _SIZE_RANK.get(str(p.get("port_size") or "").strip().lower(), 0)
        cur = by_iso3.get(ref.iso3)
        if cur is None:
            by_iso3[ref.iso3] = {"port": p, "ref": ref, "rank": rank}
            continue
        cur_rank = cur["rank"]
        if (rank, _depth_field_count(p)) > (cur_rank, _depth_field_count(cur["port"])):
            by_iso3[ref.iso3] = {"port": p, "ref": ref, "rank": rank}

    rows: list[dict] = []
    for iso3, best in by_iso3.items():
        p, ref = best["port"], best["ref"]
        override = PRIORITY_PORT_OVERRIDES.get(iso3)
        if override:
            rows.append({
                "iso3": iso3, "name_en": ref.name_en, "main_port": override,
                "port_type": "sea", "logistics_note": _OVERRIDE_NOTE,
                "source": f"{_SEA_SOURCE} + معرفة عامة",
                "source_url": _SEA_SOURCE_URL,
            })
            continue
        size = p.get("port_size") or "غير مصنَّف"
        rows.append({
            "iso3": iso3, "name_en": ref.name_en,
            "main_port": p.get("wpi_port_name") or p.get("point_of_interest") or "",
            "port_type": "sea", "logistics_note": f"تصنيف الحجم: {size}",
            "source": _SEA_SOURCE, "source_url": _SEA_SOURCE_URL,
        })

    covered = set(by_iso3)
    for name, corridor in _LANDLOCKED_CORRIDORS.items():
        ref, _sugg = resolve_market(name)
        if ref is None or ref.iso3 in covered:
            continue
        rows.append({
            "iso3": ref.iso3, "name_en": ref.name_en, "main_port": corridor,
            "port_type": "landlocked_corridor",
            "logistics_note": ("ممرّ عبور معتاد (معلومة جغرافية-لوجستية عامة "
                              "— تحقق من شروط العبور الحالية قبل الشحن)"),
            "source": "معلومة جغرافية عامة — general logistics knowledge",
            "source_url": "",
        })

    if unmatched:
        log.warning("port-index country names unmatched to an iso3 (%d): %s",
                   len(unmatched), sorted(unmatched))
    return rows


def write_csv(rows: list[dict], path: str) -> None:
    fp = path if os.path.isabs(path) else os.path.join(_HERE, path)
    rows = sorted(rows, key=lambda r: r["iso3"])
    with open(fp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default="data/ports_l1.csv")
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
    sea = sum(1 for r in rows if r["port_type"] == "sea")
    corridor = len(rows) - sea
    log.info("wrote %d rows to %s (%d sea ports, %d landlocked corridors)",
             len(rows), args.path, sea, corridor)
    return 0


if __name__ == "__main__":
    sys.exit(main())

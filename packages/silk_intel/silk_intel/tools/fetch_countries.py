#!/usr/bin/env python3
"""جالب مرجع الدول العالمي — fetch the worldwide country reference table.

Pulls the public-domain mledoze/countries dataset (compiled from ISO 3166-1,
UN M49, and Wikipedia; MIT-licensed, https://github.com/mledoze/countries)
and maps each entry to a row {iso3, m49, name_en, name_ar, aliases, region,
source_url} for data/countries.csv. m49 numeric codes equal ISO 3166-1
numeric codes for country-level entries (Saudi Arabia = 682 matches the
existing silk_market_ranker._SAUDI_M49 constant) — no separate UN M49 fetch
needed. Rows lacking a numeric code (one dependent territory as of writing)
keep m49 empty rather than a guessed value.

NETWORK REQUIRED / يتطلب إنترنت: on any fetch/parse failure this prints a
clear message and exits non-zero — it NEVER writes fabricated rows (same
discipline as tools/fetch_hs_codes.py).

Usage:
    python3 tools/fetch_countries.py [--path data/countries.csv] [--url URL]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys

log = logging.getLogger(__name__)

DEFAULT_URL = ("https://raw.githubusercontent.com/mledoze/countries/master/"
               "dist/countries.json")
SOURCE_URL = "https://github.com/mledoze/countries"

# أسماء شائعة غائبة عن مlédoze (تبنّت الأمم المتحدة "Türkiye" رسمياً ٢٠٢٢
# فحذفت "Turkey" من الأسماء المعتمدة) — إضافة يدوية صغيرة لأسماء شائعة
# الاستعمال حقيقياً، لا اختلاق بيانات إحصائية. Common-usage name gaps.
ALIAS_OVERRIDES: dict[str, list[str]] = {
    "TUR": ["Turkey"],
}
FIELDNAMES = ["iso3", "iso2", "m49", "name_en", "name_ar", "aliases", "region",
             "source_url"]


def _arabic_name(entry: dict) -> tuple[str, str]:
    """الاسم العربي (شائع/رسمي) — Arabic common+official name for ANY country.

    `translations.ara` covers every entry (the Arabic *translation* of the
    country's name, maintained by the dataset for all ~250 rows) — unlike
    `name.native.ara`, which only exists for countries where Arabic is a
    native/official language (~25 of them). Translation prefers translations.
    """
    trans = (entry.get("translations") or {}).get("ara") or {}
    native = ((entry.get("name") or {}).get("native") or {}).get("ara") or {}
    common = (trans.get("common") or native.get("common") or "").strip()
    official = (trans.get("official") or native.get("official") or "").strip()
    return common, official


def _aliases(entry: dict, name_ar: str, official_ar: str, iso3: str) -> str:
    """اجمع أسماء بديلة للمطابقة — common/official EN+AR + a few altSpellings.

    Semicolon-separated, de-duplicated, ordered; feeds the resolver's exact +
    fuzzy matching (not a source-cited fact, just name variants for lookup).
    """
    name = entry.get("name") or {}
    seen: list[str] = []
    for cand in (name.get("common"), name.get("official"), name_ar,
                official_ar, *(entry.get("altSpellings") or [])[:5],
                *ALIAS_OVERRIDES.get(iso3, [])):
        c = (cand or "").strip()
        if c and c not in seen:
            seen.append(c)
    return ";".join(seen)


def map_reference(payload: list[dict]) -> list[dict]:
    """حوّل استجابة مlédoze إلى صفوف — map the raw JSON array into CSV rows."""
    rows: list[dict] = []
    for entry in payload:
        iso3 = str(entry.get("cca3") or "").strip()
        if not iso3 or len(iso3) != 3:
            continue
        name = entry.get("name") or {}
        name_ar, official_ar = _arabic_name(entry)
        rows.append({
            "iso3": iso3,
            "iso2": str(entry.get("cca2") or "").strip(),
            "m49": str(entry.get("ccn3") or "").strip(),
            "name_en": (name.get("common") or "").strip(),
            "name_ar": name_ar,
            "aliases": _aliases(entry, name_ar, official_ar, iso3),
            "region": (entry.get("region") or "").strip(),
            "source_url": SOURCE_URL,
        })
    return rows


def fetch(url: str = DEFAULT_URL) -> list[dict]:
    import requests  # lazy: keep the module importable offline
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list) or not payload:
        raise ValueError("unexpected payload shape (expected a JSON array)")
    return payload


def write_csv(rows: list[dict], path: str) -> None:
    rows = sorted(rows, key=lambda r: r["iso3"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default="data/countries.csv")
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args()
    try:
        payload = fetch(args.url)
        rows = map_reference(payload)
    except Exception as e:  # noqa: BLE001 — clear failure, never fabricate
        log.error("fetch/parse failed: %s: %s", type(e).__name__, e)
        return 1
    if not rows:
        log.error("zero rows mapped from payload — refusing to write an empty CSV")
        return 1
    write_csv(rows, args.path)
    no_m49 = [r["iso3"] for r in rows if not r["m49"]]
    log.info("wrote %d countries to %s (missing m49: %s)",
             len(rows), args.path, no_m49 or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())

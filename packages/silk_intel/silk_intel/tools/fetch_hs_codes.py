#!/usr/bin/env python3
"""جالب جدول مرجع HS الرسمي من Comtrade — fetch the official UN Comtrade HS reference table.

Pulls the public HS reference JSON, maps each entry to a row
{hs_code,name_en,name_ar,keywords} (name_ar/keywords left empty for auto-pulled
rows), and MERGES it into data/hs_codes.csv via
silk_hs_resolver.extend_from_comtrade_rows() (skips codes already present).

NETWORK REQUIRED / يتطلب إنترنت: this script calls the UN Comtrade reference
endpoint. On any network/parse failure it prints a clear message and exits
non-zero — it NEVER writes fabricated codes.

Usage:
    python3 tools/fetch_hs_codes.py [--path data/hs_codes.csv] [--url URL]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

log = logging.getLogger(__name__)

# allow running as a standalone script from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Official UN Comtrade HS classification reference (all HS editions, flat list).
DEFAULT_URL = "https://comtradeapi.un.org/files/v1/app/reference/HS.json"


def _is_hs6(code: str) -> bool:
    """هل الرمز HS6 صالح — true only for a clean 6-digit numeric HS code."""
    return len(code) == 6 and code.isdigit()


def map_reference(payload: dict) -> list[dict]:
    """حوّل استجابة المرجع إلى صفوف — map the reference JSON into HS6 rows.

    Comtrade reference shape: {"results": [{"id": "080410", "text": "..."}, ...]}.
    Keeps only 6-digit codes; name_ar/keywords are intentionally empty.
    """
    results = (payload or {}).get("results") or []
    rows: list[dict] = []
    seen: set[str] = set()
    for item in results:
        code = str(item.get("id", "")).strip()
        if not _is_hs6(code) or code in seen:
            continue
        text = str(item.get("text", "")).strip()
        # reference text is often "080410 - Dates, fresh or dried"
        name = text.split(" - ", 1)[1].strip() if " - " in text else text
        rows.append({"hs_code": code, "name_en": name, "name_ar": "", "keywords": ""})
        seen.add(code)
    return rows


def fetch_reference(url: str = DEFAULT_URL) -> list[dict]:
    """اجلب جدول المرجع عبر الشبكة — fetch + map the HS reference (raises on failure)."""
    import requests  # imported lazily so the module imports with no network/dep

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return map_reference(resp.json())


def main(argv: list[str] | None = None) -> int:
    """نقطة الدخول — CLI entry: fetch, merge, report count added."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Fetch official Comtrade HS reference and merge into the seed CSV.")
    ap.add_argument("--path", default="data/hs_codes.csv", help="CSV seed to merge into.")
    ap.add_argument("--url", default=DEFAULT_URL, help="Comtrade HS reference URL.")
    args = ap.parse_args(argv)

    try:
        rows = fetch_reference(args.url)
    except Exception as exc:  # network/parse/JSON — never fabricate, exit non-zero
        print(f"ERROR: failed to fetch HS reference from {args.url}: {exc}", file=sys.stderr)
        print("No data written. Check your internet connection and retry.", file=sys.stderr)
        return 1

    if not rows:
        print("ERROR: reference returned no usable HS6 rows; nothing written.", file=sys.stderr)
        return 1

    import silk_hs_resolver

    added = silk_hs_resolver.extend_from_comtrade_rows(rows, path=args.path)
    print(f"Fetched {len(rows)} HS6 reference rows; merged {added} new into {args.path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

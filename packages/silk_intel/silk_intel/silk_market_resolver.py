"""مُحلِّل السوق العالمي لسِلك — Silk worldwide market resolver (V5 wave 1).

يحوّل مدخلاً بشرياً (اسم إنجليزي/عربي/رمز ISO3) إلى `MarketRef` — بنفس
انضباط `silk_hs_resolver`: مطابقة تامة ثم تقريبية (difflib، بلا تبعية)،
ومطابقة ضعيفة تعيد `None` + اقتراحات بدل تخمين صامت. البذرة `data/countries.csv`
(٢٥٠ صفاً، ISO3/M49 حقيقيان من مlédoze/countries) تُبنى عبر
`tools/fetch_countries.py` — لا رموز مختلقة.
"""
from __future__ import annotations

import csv
import difflib
import functools
import os
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_PATH = os.path.join(_HERE, "data", "countries.csv")


@dataclass(frozen=True)
class MarketRef:
    """مرجع سوق محلول — a resolved market: every downstream tool takes this,
    never a raw string (single source of truth for iso3/m49/name)."""

    iso3: str
    m49: str
    name_en: str
    name_ar: str
    iso2: str = ""
    region: str = ""
    match_score: float = 1.0


def _abspath(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_HERE, path)


@functools.lru_cache(maxsize=1)
def _load(path: str = _DEFAULT_PATH) -> list[dict]:
    fp = _abspath(path)
    try:
        with open(fp, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _norm(s: str) -> str:
    """طبّع النص للمطابقة — lowercase/strip + drop periods ("U.A.E." -> "uae",
    "U.S.A." -> "usa") so abbreviated forms hit the existing alias set instead
    of falling through to a weak fuzzy score."""
    return (s or "").strip().lower().replace(".", "")


def _candidates(row: dict) -> list[str]:
    names = [row.get("iso3", ""), row.get("name_en", ""), row.get("name_ar", "")]
    names += (row.get("aliases") or "").split(";")
    return [_norm(n) for n in names if n and n.strip()]


def _to_ref(row: dict, score: float) -> MarketRef:
    return MarketRef(
        iso3=row["iso3"], m49=row.get("m49", ""), name_en=row.get("name_en", ""),
        name_ar=row.get("name_ar", ""), iso2=row.get("iso2", ""),
        region=row.get("region", ""), match_score=round(score, 2))


def resolve_market(query: str, path: str = _DEFAULT_PATH,
                   weak_threshold: float = 0.93
                   ) -> tuple[MarketRef | None, list[str]]:
    """طابق سوقاً عالمياً — exact then fuzzy match; weak match => (None, suggestions).

    Returns (MarketRef, []) on a confident match, or (None, [suggested names])
    when the best match is below `weak_threshold` — never a silent guess
    (same discipline as silk_hs_resolver.resolve_all).
    """
    q = _norm(query)
    rows = _load(path)
    if not q or not rows:
        return None, []

    # مطابقة تامة (رمز ISO3 أو اسم/لقب حرفي) — exact code/name/alias hit first.
    for row in rows:
        if q in _candidates(row):
            return _to_ref(row, 1.0), []

    # مطابقة تقريبية — best difflib ratio across each row's candidate strings.
    scored: list[tuple[float, dict]] = []
    for row in rows:
        best = max((difflib.SequenceMatcher(None, q, c).ratio()
                   for c in _candidates(row)), default=0.0)
        scored.append((best, row))
    scored.sort(key=lambda t: t[0], reverse=True)

    top_score, top_row = scored[0]
    if top_score >= weak_threshold:
        return _to_ref(top_row, top_score), []

    suggestions = [r.get("name_en", "") for _, r in scored[:5] if r.get("name_en")]
    return None, suggestions


if __name__ == "__main__":
    for q in ("nigeria", "نيجيريا", "NGA", "Nigera", "China", "الصين"):
        ref, sug = resolve_market(q)
        if ref:
            print(f"{q!r:>14} -> {ref.name_en} ({ref.iso3}/{ref.m49}) "
                  f"score={ref.match_score}")
        else:
            print(f"{q!r:>14} -> NO MATCH — suggestions: {sug}")

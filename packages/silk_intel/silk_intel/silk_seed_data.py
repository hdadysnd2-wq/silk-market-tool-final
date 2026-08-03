"""طبقة بيانات البذور الحقيقية لسِلك — Silk real bundled seed-data layer.

لقطة **حقيقية** من مؤشّرات البنك الدولي (سكان + ناتج محلي + نصيب فرد) لكل الدول،
مجلوبة من مرآة Data Packages العامة (github.com/datasets) ومُضمّنة في المستودع
(data/worldbank_seed.csv). الغرض: أن تُخرج المنصة **أرقاماً حقيقية موسومة** حتى بلا
شبكة مباشرة، وتُحدَّث حيًّا من واجهة البنك الدولي عند توفّر الوصول (fallback فقط).

المبدأ التأسيسي محفوظ: هذه قيم حقيقية بمصدر وسنة صريحين — ليست مُختلقة. عند غياب
دولة من اللقطة تُعاد None (لا تقدير). الملف يُحمّل مرة واحدة (lazy, cached).
"""
from __future__ import annotations

import csv
import logging
import os

log = logging.getLogger(__name__)

_SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "worldbank_seed.csv")
_SEED: dict[str, dict] | None = None
_SOURCE = "World Bank (لقطة مضمّنة)"  # provenance tag for seed-derived values


def _load() -> dict[str, dict]:
    """حمّل اللقطة مرة واحدة — load & cache the bundled snapshot (empty on any error)."""
    global _SEED
    if _SEED is not None:
        return _SEED
    seed: dict[str, dict] = {}
    try:
        with open(_SEED_PATH, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                iso3 = (row.get("iso3") or "").strip().upper()
                if len(iso3) == 3:
                    seed[iso3] = row
    except Exception as e:  # noqa: BLE001 — seed is a best-effort layer, never crash
        log.warning("seed data unavailable (%s): %s", _SEED_PATH, e)
    _SEED = seed
    return seed


def _num(row: dict, key: str):
    try:
        v = row.get(key)
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def available() -> bool:
    """هل اللقطة محمّلة وفيها دول؟ — is the bundled snapshot usable?"""
    return bool(_load())


def population(iso3: str):
    """سكان حقيقيون من اللقطة — real population from the snapshot: (value, year) or None."""
    row = _load().get((iso3 or "").strip().upper())
    if not row:
        return None
    v = _num(row, "population")
    return (int(v), row.get("pop_year")) if v is not None else None


def gdp_per_capita(iso3: str):
    """نصيب الفرد الحقيقي (اسمي US$) من اللقطة — real GDP/capita: (value, year) or None."""
    row = _load().get((iso3 or "").strip().upper())
    if not row:
        return None
    v = _num(row, "gdp_per_capita_usd")
    return (round(v, 2), row.get("gdp_year")) if v is not None else None


def gdp_total(iso3: str):
    """الناتج المحلي الإجمالي الحقيقي (US$) — real total GDP: (value, year) or None."""
    row = _load().get((iso3 or "").strip().upper())
    if not row:
        return None
    v = _num(row, "gdp_usd")
    return (int(v), row.get("gdp_year")) if v is not None else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk seed data — real World Bank snapshot; countries:", len(_load()))
    for c in ("ARE", "EGY", "MAR", "SAU"):
        print(f"  {c}: pop={population(c)}  gdp/cap={gdp_per_capita(c)}")

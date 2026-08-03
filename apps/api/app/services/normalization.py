"""Company-name normalization, deduplication, HS mapping, and currency conversion.

Buyer rows arrive from several sources under slightly different names; these
helpers collapse them to one canonical entry per (company, country) so the same
importer is never contacted twice.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

#: Legal-form suffixes and noise words stripped before comparison.
_LEGAL_SUFFIXES = {
    "ltd",
    "limited",
    "llc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "gmbh",
    "ag",
    "sa",
    "srl",
    "spa",
    "bv",
    "nv",
    "co",
    "company",
    "pvt",
    "private",
    "plc",
    "llp",
    "sarl",
    "sas",
    "pte",
    "est",
    "establishment",
    "wll",
}

_TRANSLIT = str.maketrans(
    {
        "à": "a",
        "á": "a",
        "â": "a",
        "ä": "a",
        "ã": "a",
        "å": "a",
        "è": "e",
        "é": "e",
        "ê": "e",
        "ë": "e",
        "ì": "i",
        "í": "i",
        "î": "i",
        "ï": "i",
        "ò": "o",
        "ó": "o",
        "ô": "o",
        "ö": "o",
        "õ": "o",
        "ù": "u",
        "ú": "u",
        "û": "u",
        "ü": "u",
        "ñ": "n",
        "ç": "c",
        "ß": "ss",
    }
)

#: Fuzzy threshold above which two names in the same country are the same firm.
DEDUP_THRESHOLD = 90

#: Static FX table (units of currency per 1 USD). A live FX feed would replace it.
FX_TO_USD = {
    "USD": 1.0,
    "SAR": 0.2667,
    "EUR": 1.08,
    "AED": 0.2723,
    "QAR": 0.2747,
    "KWD": 3.25,
    "INR": 0.012,
    "EGP": 0.021,
    "GBP": 1.27,
    "JPY": 0.0067,
}


def normalize_name(name: str) -> str:
    """Canonical key for a company name: lowercased, de-suffixed, alnum tokens."""
    lowered = name.lower().translate(_TRANSLIT)
    tokens = re.findall(r"[a-z0-9]+", lowered)
    kept = [t for t in tokens if t not in _LEGAL_SUFFIXES]
    return " ".join(kept or tokens)


def is_same_company(name_a: str, name_b: str) -> bool:
    """True when two names refer to the same firm (assumes same country)."""
    a, b = normalize_name(name_a), normalize_name(name_b)
    if not a or not b:
        return False
    if a == b:
        return True
    return fuzz.token_sort_ratio(a, b) >= DEDUP_THRESHOLD


def find_duplicate(name: str, existing: dict[str, str]) -> str | None:
    """Return the normalized key of an existing near-duplicate, if any.

    ``existing`` maps normalized_name -> original name for candidates already in
    the same country.
    """
    candidate = normalize_name(name)
    if candidate in existing:
        return candidate
    for norm in existing:
        if fuzz.token_sort_ratio(candidate, norm) >= DEDUP_THRESHOLD:
            return norm
    return None


def to_usd(amount: float, currency: str) -> float:
    """Convert an amount to USD using the static rate table."""
    rate = FX_TO_USD.get(currency.upper(), 1.0)
    return round(amount * rate, 2)


def hs_parents(code: str) -> list[str]:
    """Return the HS6 code and its HS4 and HS2 parents, longest first."""
    code = re.sub(r"\D", "", code)
    parents = []
    if len(code) >= 6:
        parents.append(code[:6])
    if len(code) >= 4:
        parents.append(code[:4])
    if len(code) >= 2:
        parents.append(code[:2])
    return parents


def hs_match_depth(product_hs: str, buyer_hs: str) -> str:
    """Deepest shared HS level between two codes: 'hs6' | 'hs4' | 'hs2' | 'none'."""
    p = re.sub(r"\D", "", product_hs)
    b = re.sub(r"\D", "", buyer_hs)
    if p[:6] == b[:6] and len(p) >= 6 and len(b) >= 6:
        return "hs6"
    if p[:4] == b[:4]:
        return "hs4"
    if p[:2] == b[:2]:
        return "hs2"
    return "none"

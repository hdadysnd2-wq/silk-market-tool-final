"""Country reference data: ISO2 names, UN M49 codes, and language defaults.

Covers the markets the MVP seeds plus the main exporting origins that show up in
competitor snapshots. Unknown codes degrade gracefully rather than raising.
"""

from __future__ import annotations

#: iso2 -> (English name, Arabic name, M49 numeric code, primary language)
COUNTRIES: dict[str, tuple[str, str, str, str]] = {
    "SA": ("Saudi Arabia", "المملكة العربية السعودية", "682", "ar"),
    "AE": ("United Arab Emirates", "الإمارات العربية المتحدة", "784", "ar"),
    "QA": ("Qatar", "قطر", "634", "ar"),
    "KW": ("Kuwait", "الكويت", "414", "ar"),
    "BH": ("Bahrain", "البحرين", "048", "ar"),
    "OM": ("Oman", "عُمان", "512", "ar"),
    "EG": ("Egypt", "مصر", "818", "ar"),
    "JO": ("Jordan", "الأردن", "400", "ar"),
    "MA": ("Morocco", "المغرب", "504", "fr"),
    "IN": ("India", "الهند", "699", "hi"),
    "PK": ("Pakistan", "باكستان", "586", "en"),
    "BD": ("Bangladesh", "بنغلاديش", "050", "en"),
    "CN": ("China", "الصين", "156", "en"),
    "JP": ("Japan", "اليابان", "392", "en"),
    "KR": ("South Korea", "كوريا الجنوبية", "410", "en"),
    "TR": ("Türkiye", "تركيا", "792", "en"),
    "DE": ("Germany", "ألمانيا", "276", "en"),
    "FR": ("France", "فرنسا", "251", "fr"),
    "NL": ("Netherlands", "هولندا", "528", "en"),
    "ES": ("Spain", "إسبانيا", "724", "es"),
    "IT": ("Italy", "إيطاليا", "381", "en"),
    "PT": ("Portugal", "البرتغال", "620", "pt"),
    "BE": ("Belgium", "بلجيكا", "056", "fr"),
    "PL": ("Poland", "بولندا", "616", "en"),
    "GB": ("United Kingdom", "المملكة المتحدة", "826", "en"),
    "US": ("United States", "الولايات المتحدة", "842", "en"),
    "CA": ("Canada", "كندا", "124", "en"),
    "BR": ("Brazil", "البرازيل", "076", "pt"),
    "MX": ("Mexico", "المكسيك", "484", "es"),
    "CL": ("Chile", "تشيلي", "152", "es"),
    "AR": ("Argentina", "الأرجنتين", "032", "es"),
    "ZA": ("South Africa", "جنوب أفريقيا", "710", "en"),
    "NG": ("Nigeria", "نيجيريا", "566", "en"),
    "KE": ("Kenya", "كينيا", "404", "en"),
    "ID": ("Indonesia", "إندونيسيا", "360", "en"),
    "MY": ("Malaysia", "ماليزيا", "458", "en"),
    "SG": ("Singapore", "سنغافورة", "702", "en"),
    "TH": ("Thailand", "تايلاند", "764", "en"),
    "VN": ("Vietnam", "فيتنام", "704", "en"),
    "AU": ("Australia", "أستراليا", "036", "en"),
}

EU_MEMBERS = {
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
}

GCC_MEMBERS = {"SA", "AE", "QA", "KW", "BH", "OM"}

_M49_TO_ISO2 = {code: iso2 for iso2, (_, _, code, _) in COUNTRIES.items()}

#: Language code -> the English name used in the drafting prompt.
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
    "hi": "Hindi",
    "ar": "Arabic",
}


def country_name(iso2: str, locale: str = "en") -> str:
    entry = COUNTRIES.get(iso2.upper())
    if not entry:
        return iso2.upper()
    return entry[1] if locale == "ar" else entry[0]


def iso2_to_m49(iso2: str) -> str:
    entry = COUNTRIES.get(iso2.upper())
    return entry[2] if entry else iso2.upper()


def m49_to_iso2(m49: str) -> str | None:
    return _M49_TO_ISO2.get(str(m49).zfill(3))


def primary_language(iso2: str) -> str:
    """Language to write outreach in for a buyer in this country.

    Arabic-speaking markets are addressed in English: it is the working language
    of GCC import desks and avoids dialect mismatch.
    """
    entry = COUNTRIES.get(iso2.upper())
    if not entry:
        return "en"
    language = entry[3]
    return "en" if language == "ar" else language


def is_eu(iso2: str) -> bool:
    return iso2.upper() in EU_MEMBERS


def is_gcc(iso2: str) -> bool:
    return iso2.upper() in GCC_MEMBERS

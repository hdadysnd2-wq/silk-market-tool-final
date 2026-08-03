"""ISO3<->ISO2 bridge for the world funnel — pure, no DB.

The funnel keys markets by alpha-3 (``importer_iso3``); the competitor/buyer
machinery uses alpha-2. An unknown code resolves to ``None`` (a declared gap,
never a fabricated code — I1), never raises.
"""

from __future__ import annotations

import pytest

from app.providers.countries import COUNTRIES, iso2_to_iso3, iso3_to_iso2

# The alpha-3 codes the demo seed + funnel actually emit.
_SEED_ISO3 = {
    "USA": "US", "DEU": "DE", "GBR": "GB", "IND": "IN", "FRA": "FR",
    "ESP": "ES", "BRA": "BR", "EGY": "EG", "SAU": "SA",
    "ARE": "AE", "NLD": "NL", "SGP": "SG", "HKG": "HK", "BEL": "BE",
}  # fmt: skip


@pytest.mark.parametrize(("iso3", "iso2"), _SEED_ISO3.items())
def test_seed_alpha3_resolves(iso3, iso2):
    assert iso3_to_iso2(iso3) == iso2


def test_unknown_alpha3_is_a_gap_not_a_guess():
    # "XXX" is the no-data marker used in the funnel tests — never fabricate one.
    assert iso3_to_iso2("XXX") is None
    assert iso3_to_iso2("") is None


def test_lookup_is_case_insensitive():
    assert iso3_to_iso2("deu") == "DE"
    assert iso2_to_iso3("de") == "DEU"


def test_round_trips_for_every_known_market():
    # Every seeded market resolves back to itself through the bridge.
    for iso2 in COUNTRIES:
        iso3 = iso2_to_iso3(iso2)
        assert iso3 is not None, f"no alpha-3 for {iso2}"
        assert iso3_to_iso2(iso3) == iso2

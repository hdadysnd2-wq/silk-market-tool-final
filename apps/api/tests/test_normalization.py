"""Company-name normalization, dedup, HS mapping, and currency conversion."""

from __future__ import annotations

import pytest

from app.services import normalization


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Acme Trading Ltd", "acme trading"),
        ("ACME GmbH", "acme"),
        ("Global Plastics LLC", "global plastics"),
        ("Société Générale SA", "societe generale"),
    ],
)
def test_normalize_name_strips_legal_forms(raw, expected):
    assert normalization.normalize_name(raw) == expected


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("Acme Trading Ltd", "ACME Trading", True),
        ("Acme Trading Ltd", "Acme Trdaing", True),
        ("Acme Trading", "Beta Distribution", False),
    ],
)
def test_is_same_company(a, b, same):
    assert normalization.is_same_company(a, b) is same


def test_find_duplicate():
    existing = {"acme trading": "acme trading", "beta imports": "beta imports"}
    assert normalization.find_duplicate("Acme Trading Ltd", existing) == "acme trading"
    assert normalization.find_duplicate("Zeta Corp", existing) is None


@pytest.mark.parametrize(
    "p,b,depth",
    [
        ("392010", "392010", "hs6"),
        ("392010", "392099", "hs4"),
        ("392010", "391000", "hs2"),
        ("392010", "847130", "none"),
    ],
)
def test_hs_match_depth(p, b, depth):
    assert normalization.hs_match_depth(p, b) == depth


def test_hs_parents():
    assert normalization.hs_parents("392010") == ["392010", "3920", "39"]


def test_currency_conversion_to_usd():
    assert normalization.to_usd(100, "USD") == 100.0
    assert normalization.to_usd(100, "SAR") == pytest.approx(26.67, abs=0.01)
    assert normalization.to_usd(100, "XYZ") == 100.0  # unknown → identity

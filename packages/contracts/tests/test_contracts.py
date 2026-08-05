"""Unified data-contract tests (D2).

``packages/contracts`` shipped with no test suite. This locks the two adapters —
in particular that composite/multi-source attribution (``source_ids``, the HF1
fix) survives ``from_datapoint``: the adapter used to read a non-existent
``sources`` attribute, silently dropping it on every adapt.

The package deliberately imports neither side, so the doubles below are plain
duck-typed stand-ins for the engine ``DataPoint`` and the platform
``ProviderRecord`` shapes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from contracts import DataContract, from_datapoint, from_provider_record, missing


@dataclass
class FakeDataPoint:
    """Mirrors the engine ``DataPoint`` fields the adapter reads."""

    value: object = None
    source: str = ""
    confidence: float = 0.0
    retrieved_at: str | None = None
    data_year: int | None = None
    note: str = ""
    status: str = ""
    source_ids: tuple[str, ...] = ()


# -- the round-trip the task asks for: source_ids must survive ---------------


def test_from_datapoint_preserves_source_ids():
    dp = FakeDataPoint(
        value=42,
        source="Comtrade",
        confidence=0.9,
        retrieved_at="2026-01-01",
        data_year=2024,
        source_ids=("comtrade:784", "wits:392010"),
    )
    contract = from_datapoint(dp, provider="comtrade")

    assert contract.sources == ("comtrade:784", "wits:392010")
    assert contract.value == 42
    assert contract.provider == "comtrade"
    assert contract.data_year == 2024
    # ...and the attribution survives the JSON/queue boundary too.
    assert contract.as_dict()["sources"] == ["comtrade:784", "wits:392010"]


def test_from_datapoint_falls_back_to_a_sources_attribute():
    """A double exposing ``sources`` (not ``source_ids``) still round-trips."""

    @dataclass
    class OldShape:
        value: object = 1
        confidence: float = 0.5
        sources: tuple[str, ...] = field(default_factory=lambda: ("a", "b"))

    assert from_datapoint(OldShape()).sources == ("a", "b")


def test_from_datapoint_no_attribution_is_empty_tuple():
    assert from_datapoint(FakeDataPoint(value=1, confidence=0.5)).sources == ()


def test_from_datapoint_missing_value_round_trips_the_gap():
    dp = FakeDataPoint(value=None, confidence=0.0, note="no key", status="no_record")
    contract = from_datapoint(dp)
    assert contract.is_missing
    assert contract.note == "no key"
    assert contract.status == "no_record"


# -- ProviderRecord side + the canonical missing() envelope ------------------


class _SourceType:
    """Stand-in for the platform ``SourceType`` enum (clean ``.value``)."""

    def __init__(self, value: str) -> None:
        self.value = value


@dataclass
class FakeProviderRecord:
    data: object = None
    source: object = ""
    provider_name: str = ""
    confidence: float = 0.0
    fetched_at: object = None


def test_from_provider_record_uses_enum_value_and_isoformats_time():
    rec = FakeProviderRecord(
        data={"x": 1},
        source=_SourceType("comtrade"),
        provider_name="comtrade",
        confidence=0.9,
        fetched_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    contract = from_provider_record(rec)
    assert contract.source == "comtrade"  # never "SourceType.COMTRADE"
    assert contract.provider == "comtrade"
    assert contract.value == {"x": 1}
    assert contract.fetched_at.startswith("2026-01-01")


def test_from_provider_record_no_payload_is_missing():
    contract = from_provider_record(FakeProviderRecord(data=None, confidence=0.9))
    assert contract.is_missing
    assert contract.confidence == 0.0


def test_missing_envelope_is_the_canonical_no_data_state():
    m = missing("Comtrade", "comtrade", "rate limited")
    assert isinstance(m, DataContract)
    assert m.value is None and m.confidence == 0.0
    assert m.is_missing and m.status == "fetch_failed"

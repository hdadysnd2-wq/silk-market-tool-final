"""ProviderRecord ↔ DataContract bridge (I1 / decision #4).

The merge unified the two provenance models onto one envelope. This proves the
platform's ``ProviderRecord`` converts to that envelope with a clean source, and
that a missing payload becomes a zero-confidence gap — never a fabricated value.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.providers.base import ExporterShare, ProviderRecord, SourceType


def test_provider_record_converts_to_a_clean_envelope():
    rec = ProviderRecord(
        data=ExporterShare(
            exporter_iso2="CN",
            exporter_name="China",
            value_usd=100.0,
            share_pct=40.0,
            year=2023,
        ),
        source=SourceType.COMTRADE,
        provider_name="comtrade",
        confidence=0.9,
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    c = rec.to_contract()

    assert c.value is not None
    assert c.source == "comtrade"  # clean enum value, never "SourceType.COMTRADE"
    assert c.provider == "comtrade"
    assert c.confidence == 0.9
    assert c.fetched_at == "2024-01-01T00:00:00+00:00"
    assert c.is_missing is False


def test_missing_payload_is_a_zero_confidence_gap():
    rec = ProviderRecord(
        data=None, source=SourceType.COMTRADE, provider_name="comtrade", confidence=0.9
    )

    c = rec.to_contract()

    # I1 — no payload ⇒ a declared gap, never a fabricated value.
    assert c.value is None
    assert c.confidence == 0.0
    assert c.is_missing is True

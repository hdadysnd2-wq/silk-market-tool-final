"""Real provider adapters degrade to their safe result on a vendor hiccup.

The real adapters are never exercised by the mock suites; these lock the
guarantee that a malformed or unexpected vendor response degrades (empty / None
/ unknown) instead of crashing the discovery pipeline (I1). A crash here is not
academic: buyer_discovery._find_contacts → waterfall.resolve → verifier.verify()
means one bad response would abort a whole market's discovery run.
"""

from __future__ import annotations

import httpx

from app.providers.base import VerificationOutcome
from app.providers.email_finding.apollo import ApolloEmailFinderProvider
from app.providers.enrichment.coresignal import CoresignalProvider
from app.providers.maps.outscraper import OutscraperMapsProvider
from app.providers.verification.zerobounce import ZeroBounceVerifier


class _Resp:
    def __init__(self, json_value=None, raises=False):
        self._json_value = json_value
        self._raises = raises

    def raise_for_status(self):
        return None

    def json(self):
        if self._raises:
            raise ValueError("not JSON")
        return self._json_value


class _Client:
    """Stand-in for httpx.Client that yields a canned response for get/post."""

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, *args, **kwargs):
        return self._resp

    def post(self, *args, **kwargs):
        return self._resp


def _patch(monkeypatch, resp):
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _Client(resp))


def test_zerobounce_non_json_degrades_to_unknown(monkeypatch):
    _patch(monkeypatch, _Resp(raises=True))
    result = ZeroBounceVerifier("key").verify("buyer@example.com")
    assert result.outcome is VerificationOutcome.unknown
    assert not result.is_sendable  # a hiccup can never leak a sendable verdict


def test_apollo_non_json_degrades_to_empty(monkeypatch):
    _patch(monkeypatch, _Resp(raises=True))
    assert ApolloEmailFinderProvider("key").find_contacts("Acme", "acme.com", "US") == []


def test_coresignal_non_json_degrades_to_none(monkeypatch):
    _patch(monkeypatch, _Resp(raises=True))
    assert CoresignalProvider("key").enrich_company("Acme", "US") is None


def test_coresignal_unexpected_shape_degrades_to_none(monkeypatch):
    # A dict instead of the assumed list of ids must not raise on ids[0].
    _patch(monkeypatch, _Resp(json_value={"unexpected": "shape"}))
    assert CoresignalProvider("key").enrich_company("Acme", "US") is None


def test_outscraper_non_json_degrades_to_empty(monkeypatch):
    _patch(monkeypatch, _Resp(raises=True))
    assert OutscraperMapsProvider("key").search_importers("importers", "US") == []


class _CapturingClient:
    """Records the last post() kwargs so auth/payload can be asserted."""

    last_kwargs: dict = {}

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, *args, **kwargs):
        _CapturingClient.last_kwargs = kwargs
        return self._resp


def test_apollo_authenticates_via_header_not_body(monkeypatch):
    resp = _Resp(json_value={"people": []})
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _CapturingClient(resp))
    ApolloEmailFinderProvider("secret-key").find_contacts("Acme", "acme.com", "US")
    kwargs = _CapturingClient.last_kwargs
    # Key travels in the X-Api-Key header, never in the JSON body.
    assert kwargs["headers"]["X-Api-Key"] == "secret-key"
    assert "api_key" not in kwargs["json"]


def test_apollo_drops_masked_and_locked_emails(monkeypatch):
    people = {
        "people": [
            {"email": "real.buyer@acme.com", "email_status": "verified", "name": "Real"},
            {"email": "email_not_unlocked@domain.com", "email_status": "locked", "name": "Masked"},
            {"email": "someone@acme.com", "email_status": "unavailable", "name": "Unavailable"},
            {"email": None, "email_status": "verified", "name": "NoEmail"},
        ]
    }
    _patch(monkeypatch, _Resp(json_value=people))
    records = ApolloEmailFinderProvider("key").find_contacts("Acme", "acme.com", "US")
    # Only the genuinely revealed address survives — no dead/masked leads stored.
    assert [r.data.email for r in records] == ["real.buyer@acme.com"]


# --- Paid per-buyer vendor calls must charge the analysis budget and degrade
# --- (never make the call) once the ceiling is reached. Only the LIVE adapters
# --- meter — mocks/offline are unaffected (mirrors comtrade). Audit finding M3.

from app.services.api_budget import budget_scope  # noqa: E402


class _ProbeClient:
    """Records whether an httpx.Client was constructed and answers get/post."""

    constructed = 0

    def __init__(self, resp):
        _ProbeClient.constructed += 1
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, *a, **k):
        return self._resp

    def post(self, *a, **k):
        return self._resp


def _probe(monkeypatch, resp):
    _ProbeClient.constructed = 0
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _ProbeClient(resp))


def test_coresignal_skips_paid_call_when_budget_exhausted(monkeypatch):
    _probe(monkeypatch, _Resp(json_value=[]))
    with budget_scope(limit=0):
        result = CoresignalProvider("key").enrich_company("Acme", "US")
    assert result is None
    assert _ProbeClient.constructed == 0  # the paid HTTP call never happened


def test_apollo_skips_paid_call_when_budget_exhausted(monkeypatch):
    _probe(monkeypatch, _Resp(json_value={"people": []}))
    with budget_scope(limit=0):
        assert ApolloEmailFinderProvider("key").find_contacts("Acme", "acme.com", "US") == []
    assert _ProbeClient.constructed == 0


def test_zerobounce_skips_paid_call_when_budget_exhausted(monkeypatch):
    _probe(monkeypatch, _Resp(json_value={"status": "valid"}))
    with budget_scope(limit=0):
        result = ZeroBounceVerifier("key").verify("buyer@example.com")
    assert result.outcome is VerificationOutcome.unknown  # degraded, not sendable
    assert not result.is_sendable
    assert _ProbeClient.constructed == 0


def test_paid_adapters_charge_their_source_within_budget(monkeypatch):
    # Each live adapter, when it does run, records its own budget source so
    # per-analysis spend stays attributable and capped.
    with budget_scope(limit=10) as budget:
        _probe(monkeypatch, _Resp(json_value=[]))  # empty search → None, but charged
        CoresignalProvider("key").enrich_company("Acme", "US")
        _probe(monkeypatch, _Resp(json_value={"people": []}))
        ApolloEmailFinderProvider("key").find_contacts("Acme", "acme.com", "US")
        _probe(monkeypatch, _Resp(json_value={"status": "valid"}))
        ZeroBounceVerifier("key").verify("buyer@example.com")
    assert budget.spent_by_source == {
        "enrichment": 1,
        "email_finding": 1,
        "verification": 1,
    }

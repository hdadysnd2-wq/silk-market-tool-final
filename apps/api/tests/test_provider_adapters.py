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

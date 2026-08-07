"""قفل C6 (تدقيق 2026-08-07): سطح النشر القديم للمحرّك مُحيَّد.

Lock for audit 2026-08-07 C6: the engine's legacy standalone deployment surface
is neutralized — serving without SILK_API_KEY fails closed, and the pre-merge
deploy artifacts (railway.json / netlify.toml / Dockerfile) that invited an
accidental open deployment stay deleted.
"""
import os

import pytest

_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_create_app_refuses_keyless_without_explicit_open_dev(monkeypatch):
    import api

    monkeypatch.delenv("SILK_API_KEY", raising=False)
    monkeypatch.delenv("SILK_ALLOW_OPEN_DEV", raising=False)
    with pytest.raises(RuntimeError, match="SILK_API_KEY"):
        api.create_app()


def test_create_app_serves_with_key(monkeypatch):
    import api

    monkeypatch.setenv("SILK_API_KEY", "test-service-key")
    monkeypatch.delenv("SILK_ALLOW_OPEN_DEV", raising=False)
    app = api.create_app()
    assert app is not None


def test_create_app_serves_with_explicit_open_dev(monkeypatch):
    import api

    monkeypatch.delenv("SILK_API_KEY", raising=False)
    monkeypatch.setenv("SILK_ALLOW_OPEN_DEV", "1")
    assert api.create_app() is not None


def test_premerge_deploy_artifacts_stay_deleted():
    for name in ("railway.json", "netlify.toml", "Dockerfile"):
        path = os.path.join(_PKG_DIR, name)
        assert not os.path.exists(path), (
            f"{name} must not return to packages/silk_intel/silk_intel/ — it "
            "invites deploying the superseded standalone server (C6)"
        )

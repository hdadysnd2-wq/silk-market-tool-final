"""Regression locks for cross-container image storage (audit blocker #7).

The worker's vision pass loaded images from ``product.image_url`` — a ``file://``
path on the API container's disk that a separate worker container cannot read, so
on the documented default deploy the photo was stored but never analyzed, with no
signal. Images are now fetched by a backend-agnostic storage ``key`` through the
storage interface, an unreadable image is logged loudly, and the S3→local silent
fallback is gone.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.models import Product
from app.providers.llm.mock import MockLLMProvider
from app.services import storage as storage_mod
from app.services.product_vision import _load_image, describe_product


class _KeyOnlyStorage:
    """Storage stub that only answers by key (mimics S3 across containers)."""

    def __init__(self):
        self._objects: dict[str, bytes] = {}

    def put(self, key, data, content_type="application/octet-stream"):
        self._objects[key] = data
        return f"s3://bucket/{key}"

    def get_bytes(self, key):
        return self._objects.get(key)


def test_load_image_fetches_by_key_through_storage(db, factory, monkeypatch):
    store = _KeyOnlyStorage()
    store.put("products/abc.png", b"PNGDATA")
    monkeypatch.setattr(storage_mod, "get_storage", lambda *a, **k: store)

    product = Product(
        factory_id=factory.id,
        name_ar="منتج",
        name_en="Widget",
        currency="USD",
        image_key="products/abc.png",
        image_url="s3://bucket/products/abc.png",  # display-only, unreadable directly
    )
    db.add(product)
    db.commit()

    data, media = _load_image(product)
    assert data == b"PNGDATA"
    assert media == "image/png"


def test_unreadable_image_logs_loudly_and_degrades(db, factory, monkeypatch):
    store = _KeyOnlyStorage()  # key not present → get_bytes returns None
    monkeypatch.setattr(storage_mod, "get_storage", lambda *a, **k: store)

    # Spy the structured ERROR so the miss is provably LOUD, not silent.
    import app.services.product_vision as pv

    errors: list[str] = []
    monkeypatch.setattr(pv.log, "error", lambda event, **kw: errors.append(event))

    product = Product(
        factory_id=factory.id,
        name_ar="منتج",
        name_en="Widget",
        currency="USD",
        image_key="products/missing.png",
    )
    db.add(product)
    db.commit()

    data, _ = _load_image(product)
    assert data is None  # degrades to text-only
    assert "product_image_unreadable" in errors  # but LOUDLY, not silently

    # The vision pass still completes text-only rather than crashing the pipeline.
    parsed = describe_product(db, product, MockLLMProvider())
    assert parsed  # produced a description from the name


def test_no_silent_fallback_when_s3_selected(monkeypatch):
    """A misconfigured s3 backend must raise, not silently write to local disk."""

    class _BoomS3:
        def __init__(self, settings):
            raise RuntimeError("no bucket")

    monkeypatch.setattr(storage_mod, "S3Storage", _BoomS3)
    with pytest.raises(RuntimeError):
        storage_mod.get_storage(Settings(storage_backend="s3"))


def test_require_object_storage_rejects_local(monkeypatch):
    with pytest.raises(RuntimeError, match="REQUIRE_OBJECT_STORAGE"):
        storage_mod.get_storage(Settings(storage_backend="local", require_object_storage=True))


def test_local_storage_roundtrips_bytes_by_key(tmp_path):
    store = storage_mod.LocalStorage(str(tmp_path))
    store.put("products/x.jpg", b"JPEGDATA")
    assert store.get_bytes("products/x.jpg") == b"JPEGDATA"
    assert store.get_bytes("products/missing.jpg") is None

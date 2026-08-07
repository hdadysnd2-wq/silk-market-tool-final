"""Object storage for product images.

Two backends behind one interface: S3/MinIO for real deployments, and a local
filesystem backend used in tests and when no object store is configured.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.config import Settings, get_settings
from app.logging import get_logger

log = get_logger(__name__)


class LocalStorage:
    backend = "local"

    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._base / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"file://{path.resolve()}"

    def url_for(self, key: str) -> str:
        return f"file://{(self._base / key).resolve()}"

    def get_bytes(self, key: str) -> bytes | None:
        """Read an object's bytes by key, or None if absent. Never raises."""
        path = self._base / key
        try:
            return path.read_bytes()
        except OSError:
            return None

    def health_check(self) -> None:
        """Round-trip one fixed probe key; raises when the disk is unwritable."""
        probe = self._base / "health" / ".probe"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"ok")
        if probe.read_bytes() != b"ok":
            raise RuntimeError("local storage probe readback mismatch")


class S3Storage:
    backend = "s3"

    def __init__(self, settings: Settings) -> None:
        import boto3

        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            try:
                self._client.create_bucket(Bucket=self._bucket)
            except Exception as exc:  # pragma: no cover - depends on live MinIO
                log.warning("s3_bucket_create_failed", error=str(exc))

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return self.url_for(key)

    def url_for(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=3600
        )

    def get_bytes(self, key: str) -> bytes | None:
        """Read an object's bytes by key, or None if absent. Never raises."""
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except Exception as exc:  # noqa: BLE001 — a missing/unreadable object is a gap
            log.warning("s3_get_failed", key=key, error=str(exc))
            return None

    def health_check(self) -> None:
        """head_bucket against our own S3/MinIO; raises when unreachable/denied."""
        self._client.head_bucket(Bucket=self._bucket)


def get_storage(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.storage_backend == "s3":
        # No silent fallback to local: a misconfigured object store on a
        # multi-container deploy would otherwise write images to a disk the worker
        # cannot read (the image would be stored but never analyzed). Fail loudly.
        return S3Storage(settings)
    if settings.require_object_storage:
        raise RuntimeError(
            "STORAGE_BACKEND=local but REQUIRE_OBJECT_STORAGE=1: a multi-container "
            "deploy must use object storage (s3), or the worker cannot read images "
            "the api wrote. Configure STORAGE_BACKEND=s3 with S3/MinIO credentials."
        )
    return LocalStorage(settings.storage_local_dir)


def new_image_key(filename: str) -> str:
    suffix = Path(filename).suffix or ".bin"
    return f"products/{uuid.uuid4().hex}{suffix}"

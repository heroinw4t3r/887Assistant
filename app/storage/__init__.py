"""Pluggable blob storage package.

Public API::

    from app.storage import StorageBackend, StorageError, get_storage_backend

``get_storage_backend(settings)`` returns a process-wide singleton chosen from
configuration: an :class:`~app.storage.s3.S3StorageBackend` when
``storage_backend == "s3"`` (and the bucket + credentials are present), otherwise
a :class:`~app.storage.local.LocalStorageBackend` rooted at ``file_storage_path``.
"""
from __future__ import annotations

from app.storage.base import StorageBackend, StorageError
from app.storage.local import LocalStorageBackend

_backend: StorageBackend | None = None


def _build_backend(settings) -> StorageBackend:
    if (
        settings.storage_backend == "s3"
        and settings.s3_bucket
        and settings.s3_access_key_id
        and settings.s3_secret_access_key
    ):
        # Imported lazily so environments without S3 configured never need boto3.
        from app.storage.s3 import S3StorageBackend

        return S3StorageBackend(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
            public_base_url=settings.s3_public_base_url,
        )
    return LocalStorageBackend(settings.file_storage_path)


def get_storage_backend(settings) -> StorageBackend:
    """Return the shared storage backend, building it once on first use."""
    global _backend
    if _backend is None:
        _backend = _build_backend(settings)
    return _backend


def reset_storage_backend() -> None:
    """Clear the cached backend (primarily for tests)."""
    global _backend
    _backend = None


__all__ = [
    "StorageBackend",
    "StorageError",
    "get_storage_backend",
    "reset_storage_backend",
]

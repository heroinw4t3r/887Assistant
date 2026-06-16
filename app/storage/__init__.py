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
            force_path_style=settings.s3_force_path_style,
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


def storage_status(settings) -> tuple[str, str]:
    """Return ``(active_backend_name, human_description)`` for the active backend.

    The description is safe to log: it never includes secret values, only the
    non-sensitive endpoint/bucket/region/path-style (for s3) or the path (local).
    """
    backend = get_storage_backend(settings)
    if backend.name == "s3":
        endpoint = settings.s3_endpoint_url or "(AWS default endpoint)"
        description = (
            f"S3-compatible object storage: endpoint={endpoint} "
            f"bucket={settings.s3_bucket!r} region={settings.s3_region} "
            f"path_style={settings.s3_force_path_style}"
        )
    else:
        description = f"local filesystem: path={settings.file_storage_path!r}"
    return backend.name, description


async def check_storage(settings, logger) -> None:
    """Log the active storage backend and verify connectivity (never crashes startup)."""
    backend = get_storage_backend(settings)
    name, description = storage_status(settings)

    if settings.storage_backend == "s3" and name != "s3":
        missing = [
            field
            for field, value in (
                ("s3_bucket", settings.s3_bucket),
                ("s3_access_key_id", settings.s3_access_key_id),
                ("s3_secret_access_key", settings.s3_secret_access_key),
            )
            if not value
        ]
        logger.warning(
            "STORAGE_BACKEND=s3 was requested but required S3 settings are missing "
            "(%s); falling back to local storage. Storj/S3 is NOT being used.",
            ", ".join(missing) or "unknown",
        )

    logger.info("Active storage backend: '%s' — %s", name, description)

    try:
        await backend.healthcheck()
    except StorageError as exc:
        logger.error("Storage backend '%s' connection FAILED: %s", name, exc)
    else:
        logger.info("Storage backend '%s' connection OK", name)


__all__ = [
    "StorageBackend",
    "StorageError",
    "get_storage_backend",
    "reset_storage_backend",
    "storage_status",
    "check_storage",
]

"""Storage backend interface.

Defines the abstract contract every blob storage backend must satisfy. The
files module talks only to this interface so the concrete backend (local disk,
S3 / Cloudflare R2, …) can be swapped via configuration without touching the
business logic.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class StorageError(Exception):
    """Raised when a storage backend operation fails."""


@runtime_checkable
class StorageBackend(Protocol):
    """A pluggable blob store keyed by an opaque object key."""

    name: str

    async def save(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        """Persist ``data`` under ``key`` (overwriting any existing object)."""
        ...

    async def load(self, key: str) -> bytes:
        """Return the bytes stored under ``key``; raise :class:`StorageError` if missing."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the object stored under ``key`` (no error if it is already gone)."""
        ...

    def public_url(self, key: str) -> str | None:
        """Return a publicly reachable URL for ``key`` if configured, else ``None``."""
        ...

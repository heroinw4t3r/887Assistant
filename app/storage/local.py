"""Local-filesystem storage backend.

Stores each blob at ``base_path/<key>``. Object keys may contain ``/`` to build
a nested directory layout (e.g. ``<owner_id>/<uuid>_<name>``); intermediate
directories are created on demand. This backend has no concept of a public URL.
"""
from __future__ import annotations

import asyncio
import os

from app.storage.base import StorageError


class LocalStorageBackend:
    """Persist blobs on the local disk under ``base_path``."""

    name = "local"

    def __init__(self, base_path: str) -> None:
        self._base_path = base_path

    def _full_path(self, key: str) -> str:
        return os.path.join(self._base_path, key)

    async def save(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        path = self._full_path(key)

        def _write() -> None:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:  # pragma: no cover - exercised via StorageError tests
            raise StorageError(f"failed to write {key!r}: {exc}") from exc

    async def load(self, key: str) -> bytes:
        path = self._full_path(key)

        def _read() -> bytes:
            with open(path, "rb") as fh:
                return fh.read()

        try:
            return await asyncio.to_thread(_read)
        except OSError as exc:
            raise StorageError(f"failed to read {key!r}: {exc}") from exc

    async def delete(self, key: str) -> None:
        path = self._full_path(key)

        def _remove() -> None:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

        try:
            await asyncio.to_thread(_remove)
        except OSError as exc:
            raise StorageError(f"failed to delete {key!r}: {exc}") from exc

    def public_url(self, key: str) -> str | None:
        return None

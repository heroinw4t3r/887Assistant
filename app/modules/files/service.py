"""Files module — pure database logic.

This layer is deliberately free of any Telegram / aiogram imports so it can be
unit-tested in isolation. Every function takes an :class:`AsyncSession` and never
commits on its own unless the caller's session scope does (the shared
``session_scope`` context manager handles commit/rollback).

Access control is enforced everywhere: every query is scoped by ``owner_id`` so a
user can only ever see or mutate their own files.
"""
from __future__ import annotations

import os

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StoredFile


async def save_file(
    session: AsyncSession,
    owner_id: int,
    *,
    file_name: str,
    mime_type: str | None,
    size: int,
    telegram_file_id: str,
    kind: str,
    storage_path: str | None = None,
) -> StoredFile:
    """Persist a new file record and return it (with its generated id)."""
    stored = StoredFile(
        owner_id=owner_id,
        file_name=file_name,
        mime_type=mime_type,
        size=size,
        telegram_file_id=telegram_file_id,
        kind=kind,
        storage_path=storage_path,
    )
    session.add(stored)
    await session.flush()
    await session.refresh(stored)
    return stored


async def list_files(
    session: AsyncSession,
    owner_id: int,
    *,
    offset: int = 0,
    limit: int = 5,
    query: str | None = None,
) -> tuple[list[StoredFile], int]:
    """Return a page of the user's files plus the total matching count.

    ``query`` (when given) filters by ``file_name`` using a case-insensitive
    ``LIKE`` match.
    """
    conditions = [StoredFile.owner_id == owner_id]
    if query:
        like = f"%{query.strip()}%"
        conditions.append(StoredFile.file_name.ilike(like))

    total_stmt = select(func.count()).select_from(StoredFile).where(*conditions)
    total = (await session.execute(total_stmt)).scalar_one()

    page_stmt = (
        select(StoredFile)
        .where(*conditions)
        .order_by(StoredFile.created_at.desc(), StoredFile.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await session.execute(page_stmt)).scalars().all())
    return rows, int(total)


async def get_file(session: AsyncSession, owner_id: int, file_id: int) -> StoredFile | None:
    """Fetch one file scoped to its owner (returns ``None`` if not owned)."""
    stmt = select(StoredFile).where(
        StoredFile.id == file_id, StoredFile.owner_id == owner_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def rename_file(
    session: AsyncSession, owner_id: int, file_id: int, new_name: str
) -> StoredFile | None:
    """Rename a file the user owns; returns the updated row or ``None``."""
    stored = await get_file(session, owner_id, file_id)
    if stored is None:
        return None
    stored.file_name = new_name
    await session.flush()
    await session.refresh(stored)
    return stored


async def delete_file(session: AsyncSession, owner_id: int, file_id: int) -> bool:
    """Delete a file (and its local copy, if any). Returns ``True`` on success."""
    stored = await get_file(session, owner_id, file_id)
    if stored is None:
        return False
    if stored.storage_path:
        try:
            os.remove(stored.storage_path)
        except OSError:
            # The DB record is the source of truth; ignore filesystem errors.
            pass
    await session.delete(stored)
    await session.flush()
    return True

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
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import FileFolder, StoredFile


def _safe_disk_name(name: str) -> str:
    base = os.path.basename(name or "").strip()
    base = re.sub(r"[^\w.\- ]", "_", base)
    base = base.strip().strip(".")
    return base or "file"


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
    folder_id: int | None = None,
) -> StoredFile:
    """Persist a new file record and return it (with its generated id)."""
    if folder_id is not None:
        folder = await get_folder(session, owner_id, folder_id)
        if folder is None:
            folder_id = None

    stored = StoredFile(
        owner_id=owner_id,
        folder_id=folder_id,
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
    folder_id: int | None = None,
) -> tuple[list[StoredFile], int]:
    """Return a page of the user's files plus the total matching count."""
    conditions = [StoredFile.owner_id == owner_id]
    if query:
        like = f"%{query.strip()}%"
        conditions.append(StoredFile.file_name.ilike(like))
    else:
        conditions.append(StoredFile.folder_id.is_(folder_id))

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


async def list_folders(
    session: AsyncSession,
    owner_id: int,
    *,
    parent_id: int | None = None,
) -> list[FileFolder]:
    stmt = (
        select(FileFolder)
        .where(FileFolder.owner_id == owner_id, FileFolder.parent_id.is_(parent_id))
        .order_by(FileFolder.name.asc(), FileFolder.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_folder(
    session: AsyncSession, owner_id: int, folder_id: int
) -> FileFolder | None:
    stmt = select(FileFolder).where(
        FileFolder.id == folder_id, FileFolder.owner_id == owner_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_folder(
    session: AsyncSession,
    owner_id: int,
    name: str,
    *,
    parent_id: int | None = None,
) -> FileFolder:
    clean = name.strip() or "Папка"
    if parent_id is not None:
        parent = await get_folder(session, owner_id, parent_id)
        if parent is None:
            parent_id = None
    folder = FileFolder(owner_id=owner_id, name=clean, parent_id=parent_id)
    session.add(folder)
    await session.flush()
    await session.refresh(folder)
    return folder


async def get_storage_stats(
    session: AsyncSession, owner_id: int
) -> tuple[int, int, int, int | None]:
    """Return used bytes, file count, folder count, and quota bytes (``None`` = unlimited)."""
    used_stmt = select(func.coalesce(func.sum(StoredFile.size), 0), func.count()).where(
        StoredFile.owner_id == owner_id
    )
    used, file_count = (await session.execute(used_stmt)).one()
    folder_count = (
        await session.execute(
            select(func.count())
            .select_from(FileFolder)
            .where(FileFolder.owner_id == owner_id)
        )
    ).scalar_one()
    quota = get_settings().file_storage_quota_bytes
    quota_value = None if quota <= 0 else int(quota)
    return int(used), int(file_count), int(folder_count), quota_value


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
    if stored.storage_path and os.path.isfile(stored.storage_path):
        directory = os.path.dirname(stored.storage_path)
        new_path = os.path.join(directory, f"{stored.id}_{_safe_disk_name(new_name)}")
        if new_path != stored.storage_path:
            os.rename(stored.storage_path, new_path)
            stored.storage_path = new_path
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
            pass
    await session.delete(stored)
    await session.flush()
    return True

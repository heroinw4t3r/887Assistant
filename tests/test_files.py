"""Unit tests for the files service layer (pure DB logic, no network/Telegram)."""
from __future__ import annotations

import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import User
from app.modules.files import service

OWNER_ID = 111
OTHER_ID = 222


@pytest_asyncio.fixture
async def sessionmaker_fixture():
    """An isolated in-memory SQLite engine with its own sessionmaker."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        session.add(User(id=OWNER_ID, username="owner", full_name="Owner"))
        session.add(User(id=OTHER_ID, username="other", full_name="Other"))
        await session.commit()

    yield maker
    await engine.dispose()


async def _make_file(session, owner_id, name, size=10, kind="document", storage_path=None):
    return await service.save_file(
        session,
        owner_id,
        file_name=name,
        mime_type="application/octet-stream",
        size=size,
        telegram_file_id=f"tg-{name}",
        kind=kind,
        storage_path=storage_path,
    )


async def test_save_file(sessionmaker_fixture):
    async with sessionmaker_fixture() as session:
        stored = await _make_file(session, OWNER_ID, "report.pdf", size=42)
        await session.commit()

    assert stored.id is not None
    assert stored.owner_id == OWNER_ID
    assert stored.file_name == "report.pdf"
    assert stored.size == 42
    assert stored.telegram_file_id == "tg-report.pdf"
    assert stored.storage_path is None


async def test_list_files_pagination(sessionmaker_fixture):
    async with sessionmaker_fixture() as session:
        for i in range(7):
            await _make_file(session, OWNER_ID, f"file_{i}.txt")
        await session.commit()

    async with sessionmaker_fixture() as session:
        page1, total = await service.list_files(session, OWNER_ID, offset=0, limit=5)
        assert total == 7
        assert len(page1) == 5

        page2, total2 = await service.list_files(session, OWNER_ID, offset=5, limit=5)
        assert total2 == 7
        assert len(page2) == 2

        # No overlap between pages.
        ids1 = {f.id for f in page1}
        ids2 = {f.id for f in page2}
        assert ids1.isdisjoint(ids2)


async def test_list_files_query_case_insensitive(sessionmaker_fixture):
    async with sessionmaker_fixture() as session:
        await _make_file(session, OWNER_ID, "Vacation.JPG")
        await _make_file(session, OWNER_ID, "invoice.pdf")
        await _make_file(session, OWNER_ID, "notes.txt")
        await session.commit()

    async with sessionmaker_fixture() as session:
        files, total = await service.list_files(session, OWNER_ID, query="vacation")
        assert total == 1
        assert files[0].file_name == "Vacation.JPG"

        files, total = await service.list_files(session, OWNER_ID, query="O")
        # "Vacation", "invoice", "notes" all contain an 'o'/'O'.
        assert total == 3


async def test_list_files_only_own(sessionmaker_fixture):
    async with sessionmaker_fixture() as session:
        await _make_file(session, OWNER_ID, "mine.txt")
        await _make_file(session, OTHER_ID, "theirs.txt")
        await session.commit()

    async with sessionmaker_fixture() as session:
        files, total = await service.list_files(session, OWNER_ID)
        assert total == 1
        assert files[0].file_name == "mine.txt"


async def test_get_file_access_control(sessionmaker_fixture):
    async with sessionmaker_fixture() as session:
        stored = await _make_file(session, OWNER_ID, "secret.txt")
        await session.commit()
        file_id = stored.id

    async with sessionmaker_fixture() as session:
        # Owner can fetch it.
        assert (await service.get_file(session, OWNER_ID, file_id)) is not None
        # A different owner cannot.
        assert (await service.get_file(session, OTHER_ID, file_id)) is None
        # Missing id returns None.
        assert (await service.get_file(session, OWNER_ID, 999999)) is None


async def test_rename_file(sessionmaker_fixture):
    async with sessionmaker_fixture() as session:
        stored = await _make_file(session, OWNER_ID, "old.txt")
        await session.commit()
        file_id = stored.id

    async with sessionmaker_fixture() as session:
        renamed = await service.rename_file(session, OWNER_ID, file_id, "new.txt")
        await session.commit()
        assert renamed is not None
        assert renamed.file_name == "new.txt"

        # Cannot rename someone else's file.
        assert (await service.rename_file(session, OTHER_ID, file_id, "hax.txt")) is None

    async with sessionmaker_fixture() as session:
        stored = await service.get_file(session, OWNER_ID, file_id)
        assert stored.file_name == "new.txt"


async def test_delete_file(sessionmaker_fixture, tmp_path):
    local = tmp_path / "blob.bin"
    local.write_bytes(b"data")
    assert os.path.exists(local)

    async with sessionmaker_fixture() as session:
        stored = await _make_file(
            session, OWNER_ID, "blob.bin", storage_path=str(local)
        )
        await session.commit()
        file_id = stored.id

    async with sessionmaker_fixture() as session:
        # Other owner cannot delete.
        assert (await service.delete_file(session, OTHER_ID, file_id)) is False
        await session.commit()

    async with sessionmaker_fixture() as session:
        ok = await service.delete_file(session, OWNER_ID, file_id)
        await session.commit()
        assert ok is True

    # The local file was removed too.
    assert not os.path.exists(local)

    async with sessionmaker_fixture() as session:
        assert (await service.get_file(session, OWNER_ID, file_id)) is None


async def test_delete_file_missing_path_ignored(sessionmaker_fixture):
    async with sessionmaker_fixture() as session:
        stored = await _make_file(
            session, OWNER_ID, "ghost.bin", storage_path="/nonexistent/path/ghost.bin"
        )
        await session.commit()
        file_id = stored.id

    async with sessionmaker_fixture() as session:
        # Filesystem error on a missing path must be ignored.
        ok = await service.delete_file(session, OWNER_ID, file_id)
        await session.commit()
        assert ok is True

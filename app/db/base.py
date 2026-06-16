"""Async SQLAlchemy engine / session factory and schema initialisation."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_settings = get_settings()

engine = create_async_engine(_settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create the SQLite data directory (if needed) and all tables.

    For SQLite we use create_all for simplicity. A production PostgreSQL deployment
    would typically run Alembic migrations instead; the models are written so that
    moving to Alembic does not require business-logic changes.
    """
    # Import models so they are registered on Base.metadata before create_all.
    from app.db import models  # noqa: F401

    if _settings.is_sqlite:
        # Ensure the directory for the sqlite file exists.
        # database_url looks like sqlite+aiosqlite:///./data/887assistant.db
        path = _settings.database_url.split(":///", 1)[-1]
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional session scope."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

"""DB-backed (L2) cache for FACEIT nickname verdicts.

The :class:`FaceitClient` keeps an in-memory (L1) cache that is lost on
restart. This module persists definitive TAKEN/FREE verdicts to the
``faceit_nick_cache`` table so they survive restarts and don't re-spend the
API quota — the main capacity win for repeated bulk 3-char scans.

Backend-agnostic: works on both SQLite and PostgreSQL. Upserts are done via
``session.get`` + in-place update / ``session.add`` rather than a
dialect-specific ``ON CONFLICT``.

CONTRACT:
    async get_cached(session, nickname, ttl) -> NickResult | None
    async put_cached(session, result) -> None
    async put_many(session, results) -> None
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FaceitNickCache
from app.modules.faceit.client import NickResult, NickStatus


def _as_utc(value: datetime) -> datetime:
    """Treat naive datetimes (e.g. from SQLite) as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def get_cached(
    session: AsyncSession, nickname: str, ttl: int
) -> NickResult | None:
    """Return a cached verdict for ``nickname`` if present and fresh.

    Looks the row up by primary key. Returns a :class:`NickResult` when the
    entry exists and was checked within ``ttl`` seconds of now (UTC);
    otherwise (missing or stale) returns ``None``.
    """
    row = await session.get(FaceitNickCache, nickname)
    if row is None:
        return None

    age = (datetime.now(UTC) - _as_utc(row.checked_at)).total_seconds()
    if age > ttl:
        return None

    return NickResult(
        nickname=row.nickname,
        status=NickStatus(row.status),
        player_id=row.player_id,
    )


async def put_cached(session: AsyncSession, result: NickResult) -> None:
    """Upsert a single definitive (TAKEN/FREE) verdict.

    ERROR results are never persisted — transient failures must be retried.
    """
    if result.status is NickStatus.ERROR:
        return

    row = await session.get(FaceitNickCache, result.nickname)
    now = datetime.now(UTC)
    if row is None:
        session.add(
            FaceitNickCache(
                nickname=result.nickname,
                status=result.status.value,
                player_id=result.player_id,
                checked_at=now,
            )
        )
    else:
        row.status = result.status.value
        row.player_id = result.player_id
        row.checked_at = now


async def put_many(session: AsyncSession, results: list[NickResult]) -> None:
    """Batch upsert of definitive verdicts (skips ERROR results)."""
    for result in results:
        await put_cached(session, result)

"""FACEIT nickname-checking service layer.

Pure async orchestration + message formatting on top of :class:`FaceitClient`.
No Telegram / aiogram imports here so it stays unit-testable without network.

CONTRACT:
    async check_many(client, nicknames) -> list[NickResult]
    async bulk_scan(client, kind, *, on_progress, should_stop, length) -> list[NickResult]
    def format_free_list(results) -> list[str]
    def format_check_results(results) -> str
"""
from __future__ import annotations

import html
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.faceit.cache import get_cached, put_cached
from app.modules.faceit.charset import (
    count_digit,
    count_letter,
    iter_digit_nicknames,
    iter_letter_nicknames,
)
from app.modules.faceit.client import FaceitClient, NickResult, NickStatus

# Telegram hard limit is 4096 chars; keep a comfortable margin per chunk.
_MAX_CHUNK_CHARS = 3500
# Emit a progress callback every N processed nicknames during a bulk scan.
_PROGRESS_EVERY = 50
# Flush newly cached verdicts to the DB every N misses during a long scan so
# results survive even if the scan is stopped or crashes mid-run.
_CACHE_FLUSH_EVERY = 100

ProgressCb = Callable[[int, int, int], Awaitable[None] | None]
StopCb = Callable[[], bool]


async def _resolve(
    client: FaceitClient,
    nick: str,
    *,
    session: AsyncSession | None,
    ttl: int,
) -> tuple[NickResult, bool]:
    """Resolve a single nickname, preferring the L2 (DB) cache.

    Returns ``(result, was_cache_hit)``. On a DB-cache hit the network/rate
    limit is skipped entirely. On a miss the client is queried and a definitive
    verdict is persisted to the DB cache (errors are never cached).
    """
    if session is not None:
        cached = await get_cached(session, nick, ttl)
        if cached is not None:
            return cached, True

    result = await client.check(nick)
    if session is not None and result.status is not NickStatus.ERROR:
        await put_cached(session, result)
    return result, False


async def check_many(
    client: FaceitClient,
    nicknames: list[str],
    *,
    session: AsyncSession | None = None,
) -> list[NickResult]:
    """Check a list of nicknames sequentially (rate limited inside the client).

    When ``session`` is provided, a persistent DB-backed L2 cache is consulted
    first: cache hits skip the network and the rate limit, and fresh definitive
    verdicts are written back. When ``session`` is None, behaviour is unchanged
    (memory-only via the client).
    """
    ttl = get_settings().faceit_cache_ttl
    results: list[NickResult] = []
    for nick in nicknames:
        result, _ = await _resolve(client, nick, session=session, ttl=ttl)
        results.append(result)
    return results


async def bulk_scan(
    client: FaceitClient,
    kind: str,
    *,
    on_progress: ProgressCb | None = None,
    should_stop: StopCb | None = None,
    length: int = 3,
    session: AsyncSession | None = None,
) -> list[NickResult]:
    """Scan the entire 3-char letter or digit space.

    Iterates the matching generator, resolving each nickname through the L2
    (DB) cache when ``session`` is provided — cache hits skip the network and
    the rate limit, and fresh definitive verdicts are written back. Without a
    session it behaves as before (memory-only via the client, which still
    enforces the rate limit).

    Calls ``on_progress(done, total, free_count)`` every ``_PROGRESS_EVERY``
    items (and once at the end). Aborts early when ``should_stop()`` returns
    True, returning whatever was gathered so far. Newly cached verdicts are
    flushed to the DB periodically so they survive an early stop or a crash.
    """
    if kind == "letters":
        generator = iter_letter_nicknames(length)
        total = count_letter(length)
    elif kind == "digits":
        generator = iter_digit_nicknames(length)
        total = count_digit(length)
    else:
        raise ValueError(f"unknown bulk scan kind: {kind!r}")

    ttl = get_settings().faceit_cache_ttl
    results: list[NickResult] = []
    free_count = 0
    done = 0
    pending_writes = 0
    try:
        for nick in generator:
            if should_stop is not None and should_stop():
                break
            result, hit = await _resolve(client, nick, session=session, ttl=ttl)
            results.append(result)
            done += 1
            if not hit and session is not None and result.status is not NickStatus.ERROR:
                pending_writes += 1
            if result.status is NickStatus.FREE:
                free_count += 1
            if session is not None and pending_writes >= _CACHE_FLUSH_EVERY:
                await session.commit()
                pending_writes = 0
            if on_progress is not None and done % _PROGRESS_EVERY == 0:
                await _maybe_await(on_progress(done, total, free_count))

        if on_progress is not None:
            await _maybe_await(on_progress(done, total, free_count))
    finally:
        # Persist whatever was gathered, even on stop/crash.
        if session is not None:
            await session.commit()
    return results


async def _maybe_await(value: Awaitable[None] | None) -> None:
    if value is not None and hasattr(value, "__await__"):
        await value


def _counts(results: Sequence[NickResult]) -> tuple[int, int, int]:
    free = sum(1 for r in results if r.status is NickStatus.FREE)
    taken = sum(1 for r in results if r.status is NickStatus.TAKEN)
    error = sum(1 for r in results if r.status is NickStatus.ERROR)
    return free, taken, error


def _code(nickname: str) -> str:
    return f"<code>{html.escape(nickname)}</code>"


def format_free_list(results: Sequence[NickResult]) -> list[str]:
    """Build message chunks listing FREE nicknames (each tap-to-copy ``<code>``).

    The first chunk starts with a header counting free / taken / error. Returns
    one or more strings, each kept under the Telegram length limit.
    """
    free, taken, error = _counts(results)
    free_nicks = [r.nickname for r in results if r.status is NickStatus.FREE]

    header = (
        f"📊 Итог проверки\n"
        f"✅ Свободно: <b>{free}</b>  ⛔ Занято: <b>{taken}</b>  ⚠️ Ошибок: <b>{error}</b>"
    )

    if not free_nicks:
        return [f"{header}\n\nСвободных ников не найдено."]

    chunks: list[str] = []
    current = f"{header}\n\n✅ Свободные ники:\n"
    for nick in free_nicks:
        line = _code(nick) + "\n"
        if len(current) + len(line) > _MAX_CHUNK_CHARS:
            chunks.append(current.rstrip("\n"))
            current = ""
        current += line
    if current.strip():
        chunks.append(current.rstrip("\n"))
    return chunks


def format_check_results(results: Sequence[NickResult]) -> str:
    """One line per nickname: free / taken / error, free wrapped in ``<code>``."""
    if not results:
        return "Не переданы ники для проверки."

    lines: list[str] = []
    for r in results:
        if r.status is NickStatus.FREE:
            lines.append(f"✅ {_code(r.nickname)} — свободен")
        elif r.status is NickStatus.TAKEN:
            lines.append(f"⛔ {_code(r.nickname)} — занят")
        else:
            detail = f" ({html.escape(r.detail)})" if r.detail else ""
            lines.append(f"⚠️ {_code(r.nickname)} — ошибка{detail}")
    return "\n".join(lines)

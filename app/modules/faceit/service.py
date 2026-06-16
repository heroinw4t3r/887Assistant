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

ProgressCb = Callable[[int, int, int], Awaitable[None] | None]
StopCb = Callable[[], bool]


async def check_many(client: FaceitClient, nicknames: list[str]) -> list[NickResult]:
    """Check a list of nicknames sequentially (rate limited inside the client)."""
    results: list[NickResult] = []
    for nick in nicknames:
        results.append(await client.check(nick))
    return results


async def bulk_scan(
    client: FaceitClient,
    kind: str,
    *,
    on_progress: ProgressCb | None = None,
    should_stop: StopCb | None = None,
    length: int = 3,
) -> list[NickResult]:
    """Scan the entire 3-char letter or digit space.

    Iterates the matching generator, awaiting ``client.check`` for each (which
    enforces the rate limit). Calls ``on_progress(done, total, free_count)``
    every ``_PROGRESS_EVERY`` items (and once at the end). Aborts early when
    ``should_stop()`` returns True, returning whatever was gathered so far.
    """
    if kind == "letters":
        generator = iter_letter_nicknames(length)
        total = count_letter(length)
    elif kind == "digits":
        generator = iter_digit_nicknames(length)
        total = count_digit(length)
    else:
        raise ValueError(f"unknown bulk scan kind: {kind!r}")

    results: list[NickResult] = []
    free_count = 0
    done = 0
    for nick in generator:
        if should_stop is not None and should_stop():
            break
        result = await client.check(nick)
        results.append(result)
        done += 1
        if result.status is NickStatus.FREE:
            free_count += 1
        if on_progress is not None and done % _PROGRESS_EVERY == 0:
            await _maybe_await(on_progress(done, total, free_count))

    if on_progress is not None:
        await _maybe_await(on_progress(done, total, free_count))
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

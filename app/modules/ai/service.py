"""AI chat business logic: conversation history persistence + provider calls.

History is stored as a JSON array of ``{"role": ..., "content": ...}`` objects in
``AISession.messages_json`` (the system prompt is *not* stored). It is trimmed to
the last ``settings.llm_max_history_messages`` messages on every save.
"""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import session_scope
from app.db.models import AISession
from app.modules.ai.providers import get_provider

# A concise, helpful, Russian-speaking assistant persona.
SYSTEM_PROMPT = (
    "Ты — дружелюбный и полезный ассистент в Telegram-боте. "
    "Отвечай ясно, по делу и без лишней воды. "
    "Если пользователь пишет по-русски, отвечай по-русски; "
    "форматируй ответы простым текстом без HTML-разметки."
)


def _decode(messages_json: str | None) -> list[dict]:
    if not messages_json:
        return []
    try:
        data = json.loads(messages_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, dict) and "role" in m and "content" in m]


async def _get_or_create_session(session: AsyncSession, owner_id: int) -> AISession:
    row = await session.get(AISession, owner_id)
    if row is None:
        row = AISession(owner_id=owner_id, messages_json="[]")
        session.add(row)
        await session.flush()
    return row


async def get_history(session: AsyncSession, owner_id: int) -> list[dict]:
    """Return the stored conversation history (may be empty)."""
    row = await session.get(AISession, owner_id)
    if row is None:
        return []
    return _decode(row.messages_json)


async def append_and_save(
    session: AsyncSession, owner_id: int, role: str, content: str
) -> list[dict]:
    """Append a message, trim to the configured limit, persist and return history."""
    row = await _get_or_create_session(session, owner_id)
    history = _decode(row.messages_json)
    history.append({"role": role, "content": content})

    max_messages = get_settings().llm_max_history_messages
    if max_messages and max_messages > 0:
        history = history[-max_messages:]

    row.messages_json = json.dumps(history, ensure_ascii=False)
    await session.flush()
    return history


async def reset(session: AsyncSession, owner_id: int) -> None:
    """Clear the conversation history for ``owner_id``."""
    row = await session.get(AISession, owner_id)
    if row is None:
        session.add(AISession(owner_id=owner_id, messages_json="[]"))
    else:
        row.messages_json = "[]"
    await session.flush()


async def ask(owner_id: int, user_text: str) -> str:
    """Run a full chat turn: persist the user message, call the provider, store the reply.

    Raises :class:`AIError` (re-raised) on provider failures so the handler can show a
    friendly message. On error nothing is committed (the surrounding transaction rolls
    back), so a failed turn does not pollute the stored history.
    """
    provider = get_provider(get_settings())

    async with session_scope() as session:
        await _get_or_create_session(session, owner_id)
        history = await append_and_save(session, owner_id, "user", user_text)

        # AIError propagates: session_scope rolls back, so a failed turn is not stored.
        reply = await provider.chat(history, system=SYSTEM_PROMPT)

        await append_and_save(session, owner_id, "assistant", reply)
        return reply

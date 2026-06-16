"""AI chat business logic: conversation history persistence + provider calls."""
from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import session_scope
from app.db.models import AISession
from app.modules.ai.providers import get_provider
from app.modules.ai.web_search import format_results_for_prompt, search_web

logger = logging.getLogger("ai.service")

SYSTEM_PROMPT = (
    "Ты — дружелюбный и полезный ассистент в Telegram-боте. "
    "Отвечай ясно, по делу и без лишней воды. "
    "Если пользователь пишет по-русски, отвечай по-русски; "
    "форматируй ответы простым текстом без HTML-разметки."
)

SYSTEM_PROMPT_OFFLINE = (
    SYSTEM_PROMPT
    + " У тебя нет доступа к интернету — не выдумывай актуальные факты "
    "(погода, новости, курсы и т.п.). Если нужны свежие данные, попроси "
    "пользователя включить «Интернет: вкл» в чате."
)

SYSTEM_PROMPT_ONLINE = (
    SYSTEM_PROMPT
    + " Ниже приложены свежие результаты веб-поиска. Опирайся на них при ответе, "
    "не выдумывай факты beyond этих данных. Если данных недостаточно — скажи об этом. "
    "При необходимости указывай источники (URL)."
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
    row = await session.get(AISession, owner_id)
    if row is None:
        return []
    return _decode(row.messages_json)


async def append_and_save(
    session: AsyncSession, owner_id: int, role: str, content: str
) -> list[dict]:
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
    row = await session.get(AISession, owner_id)
    if row is None:
        session.add(AISession(owner_id=owner_id, messages_json="[]"))
    else:
        row.messages_json = "[]"
    await session.flush()


async def ask(owner_id: int, user_text: str, *, web_enabled: bool = False) -> tuple[str, bool]:
    """Run a chat turn. Returns ``(reply, used_web_search)``."""
    settings = get_settings()
    provider = get_provider(settings)
    system_prompt = SYSTEM_PROMPT_OFFLINE
    used_web = False

    if settings.web_search_enabled and web_enabled:
        try:
            results = await search_web(user_text, settings)
        except Exception:  # noqa: BLE001 - search must never break the chat turn
            logger.warning("Web search failed; answering without web context", exc_info=True)
            results = []
        if results:
            used_web = True
            system_prompt = (
                SYSTEM_PROMPT_ONLINE
                + "\n\n"
                + format_results_for_prompt(user_text, results)
            )

    async with session_scope() as session:
        await _get_or_create_session(session, owner_id)
        history = await append_and_save(session, owner_id, "user", user_text)
        reply = await provider.chat(history, system=system_prompt)
        await append_and_save(session, owner_id, "assistant", reply)
        return reply, used_web

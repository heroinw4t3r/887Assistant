"""Track bot-sent messages so users can clear the chat without losing AI context."""
from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from aiogram import Bot
from aiogram.types import Message
from sqlalchemy import delete, select

from app.db.base import session_scope
from app.db.models import BotChatMessage

logger = logging.getLogger("bot.message_tracking")

_TRACKED_METHODS = (
    "send_message",
    "send_photo",
    "send_video",
    "send_audio",
    "send_voice",
    "send_document",
)


async def track_bot_message(owner_id: int, chat_id: int, message_id: int) -> None:
    if chat_id <= 0:
        return
    async with session_scope() as session:
        session.add(
            BotChatMessage(owner_id=owner_id, chat_id=chat_id, message_id=message_id)
        )


async def clear_tracked_messages(bot: Bot, owner_id: int, chat_id: int) -> int:
    """Delete tracked bot messages from Telegram and the database."""
    async with session_scope() as session:
        rows = list(
            (
                await session.execute(
                    select(BotChatMessage.message_id).where(
                        BotChatMessage.owner_id == owner_id,
                        BotChatMessage.chat_id == chat_id,
                    )
                )
            ).scalars()
        )
        await session.execute(
            delete(BotChatMessage).where(
                BotChatMessage.owner_id == owner_id,
                BotChatMessage.chat_id == chat_id,
            )
        )

    deleted = 0
    for message_id in rows:
        try:
            await bot.delete_message(chat_id, message_id)
            deleted += 1
        except Exception:  # noqa: BLE001 - message may already be gone
            logger.debug("Could not delete message %s in chat %s", message_id, chat_id)
    return deleted


def _wrap_bot_method(original: Callable[..., Any], method_name: str) -> Callable[..., Any]:
    @wraps(original)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        if isinstance(result, Message) and result.chat.id > 0:
            await track_bot_message(result.chat.id, result.chat.id, result.message_id)
        return result

    wrapper.__name__ = f"tracked_{method_name}"
    return wrapper


def patch_bot_for_message_tracking(bot: Bot) -> None:
    """Wrap common ``Bot.send_*`` methods to persist message ids for cleanup."""
    for method_name in _TRACKED_METHODS:
        original = getattr(Bot, method_name)
        setattr(bot, method_name, _wrap_bot_method(original, method_name))

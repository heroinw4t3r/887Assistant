"""AI chat module — Telegram handlers.

CONTRACT:
  * Exposes ``router`` (aiogram Router).
  * Registers a handler for callback data ``MENU_AI`` (app.bot.callbacks).
  * Uses callback prefix ``ai:`` for its own inline buttons.

Flow: opening the AI menu puts the user into the ``AIStates.chatting`` FSM state.
While in that state any plain-text message is forwarded to the configured LLM
provider and the reply is sent back. ``ai:reset`` clears the conversation.
"""
from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import MENU_AI, MENU_HOME
from app.config import get_settings
from app.db.base import session_scope
from app.modules.ai import service
from app.modules.ai.providers import AIError, get_provider

logger = logging.getLogger("ai")

router = Router(name="ai")

AI_RESET = "ai:reset"

# Telegram hard limit per message.
_MAX_MESSAGE_LEN = 4096


class AIStates(StatesGroup):
    chatting = State()


def _ai_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🧹 Сбросить диалог", callback_data=AI_RESET)
    builder.button(text="⬅️ В меню", callback_data=MENU_HOME)
    builder.adjust(1)
    return builder.as_markup()


def _mask_key(key: str) -> str:
    if not key:
        return "не задан"
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def _info_text(settings) -> str:
    provider = get_provider(settings)
    provider_name = html.escape(provider.name)
    model = html.escape(provider.model)
    masked_key = html.escape(_mask_key(settings.llm_api_key))
    return (
        "🤖 <b>ИИ-чат</b>\n\n"
        f"Провайдер: <b>{provider_name}</b>\n"
        f"Модель: <code>{model}</code>\n"
        f"Ключ API: <code>{masked_key}</code>\n\n"
        "Просто напишите сообщение — и я отвечу.\n"
        "Чтобы начать диалог заново, нажмите «🧹 Сбросить диалог»."
    )


async def _reply_chunked(message: Message, text: str) -> None:
    """Send a (possibly long) plain-text reply, splitting on Telegram's length limit."""
    text = text or "🤖 (пустой ответ)"
    chunks = [text[i : i + _MAX_MESSAGE_LEN] for i in range(0, len(text), _MAX_MESSAGE_LEN)]
    for index, chunk in enumerate(chunks):
        is_last = index == len(chunks) - 1
        await message.answer(
            chunk,
            parse_mode=None,
            reply_markup=_ai_kb() if is_last else None,
        )


@router.callback_query(F.data == MENU_AI)
async def open_ai(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AIStates.chatting)
    await callback.message.edit_text(_info_text(get_settings()), reply_markup=_ai_kb())
    await callback.answer()


@router.callback_query(F.data == AI_RESET)
async def reset_dialog(callback: CallbackQuery, state: FSMContext) -> None:
    async with session_scope() as session:
        await service.reset(session, callback.from_user.id)
    await state.set_state(AIStates.chatting)
    await callback.answer("🧹 Диалог сброшен")


@router.message(AIStates.chatting, F.text)
async def on_chat_message(message: Message, state: FSMContext) -> None:
    user_text = message.text or ""

    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception:  # noqa: BLE001 - the typing indicator is best-effort
        logger.debug("send_chat_action failed", exc_info=True)

    try:
        reply = await service.ask(message.from_user.id, user_text)
    except AIError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}", reply_markup=_ai_kb())
        return
    except Exception:
        logger.exception("Unexpected error in AI chat handler")
        await message.answer(
            "⚠️ Произошла непредвиденная ошибка. Попробуйте ещё раз позже.",
            reply_markup=_ai_kb(),
        )
        return

    await _reply_chunked(message, reply)

"""AI chat module — Telegram handlers."""
from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import MENU_AI
from app.bot.keyboards import AI_RESET, AI_WEB, ai_chat_kb
from app.config import get_settings
from app.db.base import session_scope
from app.modules.ai import service
from app.modules.ai.providers import AIError, get_provider

logger = logging.getLogger("ai")

router = Router(name="ai")

FSM_WEB_ENABLED = "ai_web_enabled"

_MAX_MESSAGE_LEN = 4096


class AIStates(StatesGroup):
    chatting = State()


def _mask_key(key: str) -> str:
    if not key:
        return "не задан"
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"


async def _get_web_enabled(state: FSMContext) -> bool:
    settings = get_settings()
    if not settings.web_search_enabled:
        return False
    data = await state.get_data()
    if FSM_WEB_ENABLED in data:
        return bool(data[FSM_WEB_ENABLED])
    return True


async def _set_web_enabled(state: FSMContext, enabled: bool) -> None:
    await state.update_data({FSM_WEB_ENABLED: enabled})


def _info_text(settings, *, web_enabled: bool) -> str:
    provider = get_provider(settings)
    provider_name = html.escape(provider.name)
    model = html.escape(provider.model)
    masked_key = html.escape(_mask_key(settings.llm_api_key))

    if not settings.web_search_enabled:
        web_line = "<b>Интернет:</b> отключён в настройках сервера."
    elif web_enabled:
        provider_name_search = html.escape(settings.web_search_provider)
        web_line = (
            f"<b>Интернет:</b> включён (поиск через {provider_name_search}). "
            "Актуальные данные подтягиваются перед ответом."
        )
    else:
        web_line = (
            "<b>Интернет:</b> выключен — ответы только из знаний модели. "
            "Нажмите «Интернет: выкл», чтобы включить."
        )

    return (
        "<b>ИИ-чат</b>\n\n"
        f"Провайдер: <b>{provider_name}</b>\n"
        f"Модель: <code>{model}</code>\n"
        f"Ключ API: <code>{masked_key}</code>\n\n"
        f"{web_line}\n\n"
        "Просто напишите сообщение — и я отвечу.\n"
        "«Сбросить диалог» — очистить историю с нейросетью.\n"
        "«В меню» — вернуться в главное меню."
    )


async def _reply_chunked(message: Message, text: str) -> None:
    text = text or "(пустой ответ)"
    chunks = [text[i : i + _MAX_MESSAGE_LEN] for i in range(0, len(text), _MAX_MESSAGE_LEN)]
    for chunk in chunks:
        await message.answer(chunk, parse_mode=None)


async def _reset_dialog(user_id: int, state: FSMContext) -> None:
    async with session_scope() as session:
        await service.reset(session, user_id)
    await state.set_state(AIStates.chatting)


async def _render_screen(message: Message, settings, *, web_enabled: bool) -> None:
    """Edit the current message to show the AI chat screen + inline controls."""
    try:
        await message.edit_text(
            _info_text(settings, web_enabled=web_enabled),
            reply_markup=ai_chat_kb(web_enabled=web_enabled),
        )
    except Exception:  # noqa: BLE001 - identical content / not modified is fine
        logger.debug("AI screen edit skipped", exc_info=True)


@router.callback_query(F.data == MENU_AI)
async def open_ai(callback: CallbackQuery, state: FSMContext) -> None:
    settings = get_settings()
    await _set_web_enabled(state, settings.web_search_enabled)
    await state.set_state(AIStates.chatting)
    web_enabled = await _get_web_enabled(state)
    await callback.message.edit_text(
        _info_text(settings, web_enabled=web_enabled),
        reply_markup=ai_chat_kb(web_enabled=web_enabled),
    )
    await callback.answer()


@router.callback_query(F.data == AI_WEB)
async def toggle_web_search(callback: CallbackQuery, state: FSMContext) -> None:
    settings = get_settings()
    if not settings.web_search_enabled:
        await callback.answer(
            "Веб-поиск отключён в настройках сервера.", show_alert=True
        )
        return

    new_value = not await _get_web_enabled(state)
    await _set_web_enabled(state, new_value)
    await _render_screen(callback.message, settings, web_enabled=new_value)
    await callback.answer("Интернет включён" if new_value else "Интернет выключен")


@router.callback_query(F.data == AI_RESET)
async def reset_dialog(callback: CallbackQuery, state: FSMContext) -> None:
    await _reset_dialog(callback.from_user.id, state)
    settings = get_settings()
    web_enabled = await _get_web_enabled(state)
    await _render_screen(callback.message, settings, web_enabled=web_enabled)
    await callback.answer("Диалог сброшен")


@router.message(AIStates.chatting, F.text)
async def on_chat_message(message: Message, state: FSMContext) -> None:
    user_text = message.text or ""
    web_enabled = await _get_web_enabled(state)

    try:
        if web_enabled and get_settings().web_search_enabled:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            status = await message.answer("Ищу в интернете…")
        else:
            status = None
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception:  # noqa: BLE001
        logger.debug("send_chat_action/status failed", exc_info=True)
        status = None

    try:
        reply, used_web = await service.ask(
            message.from_user.id,
            user_text,
            web_enabled=web_enabled,
        )
    except AIError as exc:
        if status is not None:
            try:
                await status.delete()
            except Exception:  # noqa: BLE001
                pass
        await message.answer(html.escape(str(exc)))
        return
    except Exception:
        logger.exception("Unexpected error in AI chat handler")
        if status is not None:
            try:
                await status.delete()
            except Exception:  # noqa: BLE001
                pass
        await message.answer(
            "Произошла непредвиденная ошибка. Попробуйте ещё раз позже."
        )
        return

    if status is not None:
        try:
            await status.delete()
        except Exception:  # noqa: BLE001
            pass

    if used_web:
        reply = f"Ответ с данными из интернета:\n\n{reply}"
    elif web_enabled:
        reply = (
            "По запросу ничего не найдено в интернете — ответ по знаниям модели:\n\n"
            + reply
        )

    await _reply_chunked(message, reply)

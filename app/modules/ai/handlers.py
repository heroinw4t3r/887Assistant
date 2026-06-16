"""AI chat module — Telegram handlers.

CONTRACT:
  * Exposes ``router`` (aiogram Router).
  * Registers a handler for callback data ``MENU_AI`` (app.bot.callbacks).
  * Uses callback prefix ``ai:`` for its own inline buttons.

TODO(subagent-3): chat session with provider abstraction, reset button.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.callbacks import MENU_AI
from app.bot.keyboards import back_home_kb

router = Router(name="ai")


@router.callback_query(F.data == MENU_AI)
async def open_ai(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🤖 Модуль ИИ-чата в разработке.", reply_markup=back_home_kb()
    )
    await callback.answer()

"""FACEIT module — Telegram handlers.

CONTRACT:
  * Exposes ``router`` (aiogram Router).
  * Registers a handler for callback data ``MENU_FACEIT`` (app.bot.callbacks).
  * Uses callback prefix ``fc:`` for its own inline buttons.

TODO(subagent-4): single/multi nickname check + bulk 3-char scan (letters / digits).
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.callbacks import MENU_FACEIT
from app.bot.keyboards import back_home_kb

router = Router(name="faceit")


@router.callback_query(F.data == MENU_FACEIT)
async def open_faceit(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🎮 Модуль FACEIT в разработке.", reply_markup=back_home_kb()
    )
    await callback.answer()

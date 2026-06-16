"""Calendar module — Telegram handlers.

CONTRACT:
  * Exposes ``router`` (aiogram Router).
  * Registers a handler for callback data ``MENU_CALENDAR`` (app.bot.callbacks).
  * Uses callback prefix ``cal:`` for its own inline buttons.

TODO(subagent-2): month grid, day view, event CRUD, sync instructions.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.callbacks import MENU_CALENDAR
from app.bot.keyboards import back_home_kb

router = Router(name="calendar")


@router.callback_query(F.data == MENU_CALENDAR)
async def open_calendar(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📅 Модуль календаря в разработке.", reply_markup=back_home_kb()
    )
    await callback.answer()

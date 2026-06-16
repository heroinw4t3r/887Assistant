"""Files module — Telegram handlers.

CONTRACT (do not change without updating callers):
  * Exposes ``router`` (aiogram Router).
  * Registers a handler for callback data ``MENU_FILES`` (app.bot.callbacks).
  * Uses callback prefix ``files:`` for its own inline buttons.

TODO(subagent-1): implement upload/list/download/rename/delete/search.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.callbacks import MENU_FILES
from app.bot.keyboards import back_home_kb

router = Router(name="files")


@router.callback_query(F.data == MENU_FILES)
async def open_files(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📁 Модуль файлов в разработке.", reply_markup=back_home_kb()
    )
    await callback.answer()

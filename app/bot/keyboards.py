"""Common keyboard builders."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import (
    MENU_AI,
    MENU_CALENDAR,
    MENU_FACEIT,
    MENU_FILES,
    MENU_HOME,
)


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📁 Файлы", callback_data=MENU_FILES)
    builder.button(text="📅 Календарь", callback_data=MENU_CALENDAR)
    builder.button(text="🤖 ИИ-чат", callback_data=MENU_AI)
    builder.button(text="🎮 FACEIT ники", callback_data=MENU_FACEIT)
    builder.adjust(2, 2)
    return builder.as_markup()


def back_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data=MENU_HOME)]]
    )

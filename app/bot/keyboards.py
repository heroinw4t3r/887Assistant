"""Common keyboard builders."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import (
    MENU_AI,
    MENU_CALENDAR,
    MENU_CLEAR,
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
    builder.button(text="🧹 Очистить чат", callback_data=MENU_CLEAR)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def ai_chat_kb(*, web_enabled: bool = True):
    """Persistent reply keyboard shown while the user is in AI chat mode."""
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    web_label = "🌐 Интернет: вкл" if web_enabled else "🌐 Интернет: выкл"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=web_label)],
            [KeyboardButton(text="🧹 Сбросить диалог")],
            [KeyboardButton(text="⬅️ В меню")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def back_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data=MENU_HOME)]]
    )

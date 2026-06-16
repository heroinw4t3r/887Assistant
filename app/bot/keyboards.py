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

# AI chat inline controls. Defined here to avoid a circular import with the
# AI handlers module; the handlers register callbacks for the same data.
AI_WEB = "ai:web"
AI_RESET = "ai:reset"


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Файлы", callback_data=MENU_FILES)
    builder.button(text="Календарь", callback_data=MENU_CALENDAR)
    builder.button(text="ИИ-чат", callback_data=MENU_AI)
    builder.button(text="FACEIT", callback_data=MENU_FACEIT)
    builder.button(text="Очистить чат", callback_data=MENU_CLEAR)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def ai_chat_kb(*, web_enabled: bool = True) -> InlineKeyboardMarkup:
    """Inline keyboard attached to the AI chat screen."""
    web_label = "Интернет: вкл" if web_enabled else "Интернет: выкл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=web_label, callback_data=AI_WEB)],
            [InlineKeyboardButton(text="Сбросить диалог", callback_data=AI_RESET)],
            [InlineKeyboardButton(text="В меню", callback_data=MENU_HOME)],
        ]
    )


def back_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data=MENU_HOME)]]
    )

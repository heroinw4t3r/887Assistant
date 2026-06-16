"""Main menu, /start and /help, plus the home navigation router."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import MENU_CLEAR, MENU_HOME
from app.bot.keyboards import main_menu_kb
from app.bot.message_tracking import clear_tracked_messages
from app.db.base import session_scope
from app.db.repository import get_or_create_user

router = Router(name="menu")

WELCOME = (
    "<b>887Assistant</b>\n\n"
    "Я умею:\n"
    "<b>Файлы</b> — загрузка и хранение ваших файлов\n"
    "<b>Календарь</b> — события и синхронизация с телефоном\n"
    "<b>ИИ-чат</b> — общение с нейросетью (OpenRouter / Llama и др.)\n"
    "<b>FACEIT</b> — проверка доступности никнеймов\n\n"
    "Выберите раздел:"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with session_scope() as session:
        await get_or_create_user(session, message.from_user)
    await message.answer(WELCOME, reply_markup=main_menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(WELCOME, reply_markup=main_menu_kb())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_menu_kb())


@router.callback_query(F.data == MENU_HOME)
async def open_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == MENU_CLEAR)
async def clear_chat(callback: CallbackQuery, state: FSMContext) -> None:
    deleted = await clear_tracked_messages(
        callback.bot, callback.from_user.id, callback.message.chat.id
    )
    await state.clear()
    await callback.message.answer(
        f"Удалено сообщений бота: <b>{deleted}</b>.\n"
        "Контекст ИИ-чата сохранён — диалог с нейросетью не сброшен."
    )
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer("Чат очищен")

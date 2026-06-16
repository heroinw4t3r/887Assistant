"""Files module — Telegram handlers.

CONTRACT (do not change without updating callers):
  * Exposes ``router`` (aiogram Router).
  * Registers a handler for callback data ``MENU_FILES`` (app.bot.callbacks).
  * Uses callback prefix ``files:`` for its own inline buttons.

Callback data patterns
  * ``menu:files``           -- open the files menu (shared constant)
  * ``files:list:<offset>``  -- paginated list of the user's files
  * ``files:view:<id>``      -- file detail card
  * ``files:get:<id>``       -- re-send the file by its Telegram file_id
  * ``files:ren:<id>``       -- start the rename flow (FSM)
  * ``files:del:<id>``       -- delete the file
  * ``files:search``         -- start the search flow (FSM)

FSM states (``FilesStates``)
  * ``renaming``  -- waiting for the new file name (target id kept in FSM data)
  * ``searching`` -- waiting for the search query
"""
from __future__ import annotations

import html
import os
import re
from datetime import datetime
from time import time

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import MENU_FILES, MENU_HOME
from app.bot.keyboards import back_home_kb
from app.config import get_settings
from app.db.base import session_scope
from app.db.models import StoredFile
from app.db.repository import get_or_create_user
from app.modules.files import service

router = Router(name="files")

PAGE_SIZE = 5
_NAME_BUTTON_MAX = 32


class FilesStates(StatesGroup):
    renaming = State()
    searching = State()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _human_size(num: int) -> str:
    """Render a byte count as a human-readable string."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _safe_name(name: str) -> str:
    """Strip path separators / unsafe characters from a user-supplied name."""
    base = os.path.basename(name or "").strip()
    base = re.sub(r"[^\w.\- ]", "_", base)
    base = base.strip().strip(".")
    return base or "file"


def _truncate(name: str, limit: int = _NAME_BUTTON_MAX) -> str:
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


def _files_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Мои файлы", callback_data="files:list:0")
    builder.button(text="🔎 Поиск", callback_data="files:search")
    builder.button(text="⬅️ В меню", callback_data=MENU_HOME)
    builder.adjust(2, 1)
    return builder.as_markup()


def _list_markup(
    files: list[StoredFile], total: int, offset: int, *, query: str | None = None
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for stored in files:
        builder.button(
            text=_truncate(stored.file_name),
            callback_data=f"files:view:{stored.id}",
        )
    builder.adjust(1)

    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        prev_offset = max(0, offset - PAGE_SIZE)
        nav.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"files:list:{prev_offset}")
        )
    if offset + PAGE_SIZE < total:
        next_offset = offset + PAGE_SIZE
        nav.append(
            InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"files:list:{next_offset}")
        )
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(text="📁 Файлы", callback_data=MENU_FILES),
        InlineKeyboardButton(text="⬅️ В меню", callback_data=MENU_HOME),
    )
    return builder.as_markup()


def _detail_markup(file_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬇️ Скачать", callback_data=f"files:get:{file_id}")
    builder.button(text="✏️ Переименовать", callback_data=f"files:ren:{file_id}")
    builder.button(text="🗑 Удалить", callback_data=f"files:del:{file_id}")
    builder.button(text="📥 К списку", callback_data="files:list:0")
    builder.button(text="⬅️ В меню", callback_data=MENU_HOME)
    builder.adjust(2, 1, 2)
    return builder.as_markup()


def _list_text(total: int, offset: int, *, query: str | None = None) -> str:
    if total == 0:
        if query:
            return (
                f"🔎 По запросу <b>{html.escape(query)}</b> ничего не найдено.\n"
                "Отправьте файл боту, чтобы сохранить его."
            )
        return "📭 У вас пока нет сохранённых файлов.\nОтправьте файл боту, чтобы сохранить его."
    page_from = offset + 1
    page_to = min(offset + PAGE_SIZE, total)
    header = "🔎 Результаты поиска" if query else "📥 Ваши файлы"
    return f"{header} ({page_from}\u2013{page_to} из {total}):"


def _detail_text(stored: StoredFile) -> str:
    created = stored.created_at
    when = created.strftime("%Y-%m-%d %H:%M") if isinstance(created, datetime) else "—"
    mime = html.escape(stored.mime_type) if stored.mime_type else "—"
    location = "на сервере" if stored.storage_path else "по ссылке Telegram"
    return (
        f"📄 <b>{html.escape(stored.file_name)}</b>\n"
        f"Размер: {_human_size(stored.size)}\n"
        f"Тип: {mime}\n"
        f"Категория: {html.escape(stored.kind)}\n"
        f"Хранение: {location}\n"
        f"Добавлен: {when}"
    )


def _extract_metadata(message: Message) -> tuple[str, str | None, int, str, str] | None:
    """Return (file_name, mime_type, size, telegram_file_id, kind) or ``None``."""
    ts = int(time())
    if message.document is not None:
        doc = message.document
        name = doc.file_name or f"document_{ts}"
        return name, doc.mime_type, doc.file_size or 0, doc.file_id, "document"
    if message.photo:
        photo = message.photo[-1]
        return f"photo_{ts}.jpg", "image/jpeg", photo.file_size or 0, photo.file_id, "photo"
    if message.video is not None:
        vid = message.video
        name = getattr(vid, "file_name", None) or f"video_{ts}.mp4"
        return name, vid.mime_type, vid.file_size or 0, vid.file_id, "video"
    if message.audio is not None:
        aud = message.audio
        name = getattr(aud, "file_name", None) or f"audio_{ts}.mp3"
        return name, aud.mime_type, aud.file_size or 0, aud.file_id, "audio"
    if message.voice is not None:
        voice = message.voice
        return f"voice_{ts}.ogg", voice.mime_type, voice.file_size or 0, voice.file_id, "voice"
    return None


async def _resend(bot: Bot, chat_id: int, stored: StoredFile) -> None:
    """Re-send a stored file to the user using its Telegram file_id."""
    file_id = stored.telegram_file_id
    if stored.kind == "photo":
        await bot.send_photo(chat_id, photo=file_id)
    elif stored.kind == "video":
        await bot.send_video(chat_id, video=file_id)
    elif stored.kind == "audio":
        await bot.send_audio(chat_id, audio=file_id)
    elif stored.kind == "voice":
        await bot.send_voice(chat_id, voice=file_id)
    else:
        await bot.send_document(chat_id, document=file_id)


# --------------------------------------------------------------------------- #
# Menu
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == MENU_FILES)
async def open_files(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "📁 <b>Файлы</b>\n\n"
        "Отправьте боту любой файл (документ, фото, видео, аудио или голосовое) — "
        "и он сохранит его. Ниже — ваши файлы и поиск.",
        reply_markup=_files_menu_kb(),
    )
    await callback.answer()


# --------------------------------------------------------------------------- #
# Storing incoming media (no state filter — files can be sent anytime)
# --------------------------------------------------------------------------- #
@router.message(F.document | F.photo | F.video | F.audio | F.voice)
async def store_incoming_file(message: Message, bot: Bot) -> None:
    meta = _extract_metadata(message)
    if meta is None:
        return
    file_name, mime_type, size, telegram_file_id, kind = meta
    settings = get_settings()

    async with session_scope() as session:
        await get_or_create_user(session, message.from_user)
        stored = await service.save_file(
            session,
            message.from_user.id,
            file_name=file_name,
            mime_type=mime_type,
            size=size,
            telegram_file_id=telegram_file_id,
            kind=kind,
            storage_path=None,
        )

        downloaded = False
        if 0 < size <= settings.file_max_download_bytes:
            user_dir = os.path.join(settings.file_storage_path, str(message.from_user.id))
            try:
                os.makedirs(user_dir, exist_ok=True)
                dest = os.path.join(user_dir, f"{stored.id}_{_safe_name(file_name)}")
                await bot.download(telegram_file_id, destination=dest)
                stored.storage_path = dest
                await session.flush()
                downloaded = True
            except Exception:
                # If the download fails we still keep the Telegram reference.
                stored.storage_path = None
                downloaded = False

        file_id = stored.id

    text = (
        f"✅ Файл сохранён: <b>{html.escape(file_name)}</b>\n"
        f"Размер: {_human_size(size)}"
    )
    if not downloaded:
        text += (
            "\n\nℹ️ Файл хранится по ссылке Telegram (его можно переслать заново), "
            "но не скачан на сервер."
        )

    builder = InlineKeyboardBuilder()
    builder.button(text="📄 Открыть", callback_data=f"files:view:{file_id}")
    builder.button(text="📥 Мои файлы", callback_data="files:list:0")
    builder.adjust(2)
    await message.answer(text, reply_markup=builder.as_markup())


# --------------------------------------------------------------------------- #
# List
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("files:list:"))
async def list_files_view(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        offset = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        offset = 0
    offset = max(0, offset)

    async with session_scope() as session:
        await get_or_create_user(session, callback.from_user)
        files, total = await service.list_files(
            session, callback.from_user.id, offset=offset, limit=PAGE_SIZE
        )

    await callback.message.edit_text(
        _list_text(total, offset),
        reply_markup=_list_markup(files, total, offset),
    )
    await callback.answer()


# --------------------------------------------------------------------------- #
# Detail
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("files:view:"))
async def view_file(callback: CallbackQuery) -> None:
    file_id = int(callback.data.split(":")[2])
    async with session_scope() as session:
        stored = await service.get_file(session, callback.from_user.id, file_id)
        if stored is None:
            await callback.answer("Файл не найден.", show_alert=True)
            return
        text = _detail_text(stored)

    await callback.message.edit_text(text, reply_markup=_detail_markup(file_id))
    await callback.answer()


# --------------------------------------------------------------------------- #
# Download / re-send
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("files:get:"))
async def download_file(callback: CallbackQuery, bot: Bot) -> None:
    file_id = int(callback.data.split(":")[2])
    async with session_scope() as session:
        stored = await service.get_file(session, callback.from_user.id, file_id)
        if stored is None:
            await callback.answer("Файл не найден.", show_alert=True)
            return
        # Detach a lightweight copy of the fields we need before the session closes.
        detached = StoredFile(
            id=stored.id,
            owner_id=stored.owner_id,
            file_name=stored.file_name,
            telegram_file_id=stored.telegram_file_id,
            kind=stored.kind,
        )

    await _resend(bot, callback.message.chat.id, detached)
    await callback.answer("Отправляю файл…")


# --------------------------------------------------------------------------- #
# Delete
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("files:del:"))
async def delete_file_view(callback: CallbackQuery) -> None:
    file_id = int(callback.data.split(":")[2])
    async with session_scope() as session:
        ok = await service.delete_file(session, callback.from_user.id, file_id)
        files, total = await service.list_files(
            session, callback.from_user.id, offset=0, limit=PAGE_SIZE
        )

    if not ok:
        await callback.answer("Файл не найден.", show_alert=True)
        return

    await callback.message.edit_text(
        "🗑 Файл удалён.\n\n" + _list_text(total, 0),
        reply_markup=_list_markup(files, total, 0),
    )
    await callback.answer("Удалено")


# --------------------------------------------------------------------------- #
# Rename (FSM)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("files:ren:"))
async def rename_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    file_id = int(callback.data.split(":")[2])
    async with session_scope() as session:
        stored = await service.get_file(session, callback.from_user.id, file_id)
        if stored is None:
            await callback.answer("Файл не найден.", show_alert=True)
            return
        current = stored.file_name

    await state.update_data(rename_id=file_id)
    await state.set_state(FilesStates.renaming)
    await callback.message.edit_text(
        f"✏️ Текущее имя: <b>{html.escape(current)}</b>\n\nОтправьте новое имя файла.",
        reply_markup=back_home_kb(),
    )
    await callback.answer()


@router.message(StateFilter(FilesStates.renaming), F.text)
async def rename_apply(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    file_id = data.get("rename_id")
    new_name = _safe_name(message.text)
    await state.clear()

    if file_id is None:
        await message.answer("Не удалось определить файл.", reply_markup=back_home_kb())
        return

    async with session_scope() as session:
        await get_or_create_user(session, message.from_user)
        stored = await service.rename_file(session, message.from_user.id, file_id, new_name)
        if stored is None:
            await message.answer("Файл не найден.", reply_markup=back_home_kb())
            return
        text = _detail_text(stored)

    await message.answer(
        "✅ Файл переименован.\n\n" + text,
        reply_markup=_detail_markup(file_id),
    )


# --------------------------------------------------------------------------- #
# Search (FSM)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "files:search")
async def search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FilesStates.searching)
    await callback.message.edit_text(
        "🔎 Введите часть имени файла для поиска.",
        reply_markup=back_home_kb(),
    )
    await callback.answer()


@router.message(StateFilter(FilesStates.searching), F.text)
async def search_apply(message: Message, state: FSMContext) -> None:
    query = message.text.strip()
    await state.clear()

    async with session_scope() as session:
        await get_or_create_user(session, message.from_user)
        files, total = await service.list_files(
            session, message.from_user.id, offset=0, limit=PAGE_SIZE, query=query
        )

    await message.answer(
        _list_text(total, 0, query=query),
        reply_markup=_list_markup(files, total, 0, query=query),
    )

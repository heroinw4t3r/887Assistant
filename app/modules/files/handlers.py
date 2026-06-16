"""Files module — Telegram handlers."""
from __future__ import annotations

import html
import io
import os
import re
from datetime import datetime
from time import time

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import MENU_FILES, MENU_HOME
from app.bot.keyboards import back_home_kb
from app.config import get_settings
from app.db.base import session_scope
from app.db.models import FileFolder, StoredFile
from app.db.repository import get_or_create_user
from app.modules.files import service

router = Router(name="files")

PAGE_SIZE = 5
_NAME_BUTTON_MAX = 32


class FilesStates(StatesGroup):
    renaming = State()
    searching = State()
    creating_folder = State()


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _safe_name(name: str) -> str:
    base = os.path.basename(name or "").strip()
    base = re.sub(r"[^\w.\- ]", "_", base)
    base = base.strip().strip(".")
    return base or "file"


def _truncate(name: str, limit: int = _NAME_BUTTON_MAX) -> str:
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


async def _current_folder_id(state: FSMContext) -> int | None:
    data = await state.get_data()
    folder_id = data.get("files_folder_id")
    return int(folder_id) if folder_id is not None else None


async def _set_current_folder(state: FSMContext, folder_id: int | None) -> None:
    if folder_id is None:
        await state.update_data(files_folder_id=None)
    else:
        await state.update_data(files_folder_id=folder_id)


def _files_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Мои файлы", callback_data="files:list:0")
    builder.button(text="📂 Создать папку", callback_data="files:mkdir")
    builder.button(text="💾 Место", callback_data="files:storage")
    builder.button(text="🔎 Поиск", callback_data="files:search")
    builder.button(text="⬅️ В меню", callback_data=MENU_HOME)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def _list_markup(
    files: list[StoredFile],
    folders: list[FileFolder],
    total: int,
    offset: int,
    *,
    folder_id: int | None = None,
    parent_id: int | None = None,
    query: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if query is None and folder_id is not None:
        up_data = f"files:open:{parent_id}" if parent_id is not None else "files:open:root"
        builder.button(text="⬆️ Вверх", callback_data=up_data)
        builder.adjust(1)

    for folder in folders:
        builder.button(
            text=f"📂 {_truncate(folder.name)}",
            callback_data=f"files:open:{folder.id}",
        )
    builder.adjust(1)

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
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"files:list:{prev_offset}",
            )
        )
    if offset + PAGE_SIZE < total:
        next_offset = offset + PAGE_SIZE
        nav.append(
            InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=f"files:list:{next_offset}",
            )
        )
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(text="📁 Файлы", callback_data=MENU_FILES),
        InlineKeyboardButton(text="⬅️ В меню", callback_data=MENU_HOME),
    )
    return builder.as_markup()


def _detail_markup(file_id: int, folder_id: int | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬇️ Скачать", callback_data=f"files:get:{file_id}")
    builder.button(text="✏️ Переименовать", callback_data=f"files:ren:{file_id}")
    builder.button(text="🗑 Удалить", callback_data=f"files:del:{file_id}")
    back_data = "files:list:0" if folder_id is None else f"files:open:{folder_id}"
    builder.button(text="📥 К списку", callback_data=back_data)
    builder.button(text="⬅️ В меню", callback_data=MENU_HOME)
    builder.adjust(2, 1, 2)
    return builder.as_markup()


def _list_text(
    total: int,
    offset: int,
    *,
    folder_name: str | None = None,
    query: str | None = None,
    folder_count: int = 0,
) -> str:
    location = f"📂 <b>{html.escape(folder_name)}</b>" if folder_name else "📁 <b>Корень</b>"
    if total == 0 and folder_count == 0:
        if query:
            return (
                f"🔎 По запросу <b>{html.escape(query)}</b> ничего не найдено.\n"
                "Отправьте файл боту, чтобы сохранить его."
            )
        return (
            f"{location}\n\n📭 Здесь пока пусто.\n"
            "Отправьте файл боту или создайте папку."
        )
    page_from = offset + 1 if total else 0
    page_to = min(offset + PAGE_SIZE, total) if total else 0
    if query:
        header = f"🔎 Результаты поиска по «{html.escape(query)}»"
    else:
        header = location
    parts = [header]
    if folder_count:
        parts.append(f"Папок: {folder_count}")
    if total:
        parts.append(f"Файлы ({page_from}–{page_to} из {total}):")
    return "\n".join(parts)


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


def _storage_text(used: int, file_count: int, folder_count: int, quota: int | None) -> str:
    lines = [
        "💾 <b>Хранилище</b>",
        f"Файлов: {file_count}",
        f"Папок: {folder_count}",
        f"Занято: {_human_size(used)}",
    ]
    if quota is None:
        lines.append("Лимит: без ограничений")
    else:
        free = max(0, quota - used)
        pct = min(100, int(used * 100 / quota)) if quota else 0
        lines.append(f"Лимит: {_human_size(quota)}")
        lines.append(f"Свободно: {_human_size(free)} ({100 - pct}%)")
    return "\n".join(lines)


def _extract_metadata(message: Message) -> tuple[str, str | None, int, str, str] | None:
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


async def _send_named_file(bot: Bot, chat_id: int, stored: StoredFile) -> None:
    """Re-send a file using the current display name from the database."""
    if stored.kind == "photo":
        await bot.send_photo(chat_id, photo=stored.telegram_file_id)
        return
    if stored.kind == "video":
        if stored.storage_path and os.path.isfile(stored.storage_path):
            await bot.send_video(
                chat_id,
                video=FSInputFile(stored.storage_path, filename=stored.file_name),
            )
        else:
            await bot.send_video(chat_id, video=stored.telegram_file_id)
        return
    if stored.kind == "audio":
        if stored.storage_path and os.path.isfile(stored.storage_path):
            await bot.send_audio(
                chat_id,
                audio=FSInputFile(stored.storage_path, filename=stored.file_name),
            )
        else:
            await bot.send_audio(chat_id, audio=stored.telegram_file_id)
        return
    if stored.kind == "voice":
        await bot.send_voice(chat_id, voice=stored.telegram_file_id)
        return

    if stored.storage_path and os.path.isfile(stored.storage_path):
        await bot.send_document(
            chat_id,
            document=FSInputFile(stored.storage_path, filename=stored.file_name),
        )
        return

    buffer = io.BytesIO()
    await bot.download(stored.telegram_file_id, destination=buffer)
    await bot.send_document(
        chat_id,
        document=BufferedInputFile(buffer.getvalue(), filename=stored.file_name),
    )


async def _render_list(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    offset: int = 0,
    query: str | None = None,
) -> None:
    folder_id = await _current_folder_id(state)
    async with session_scope() as session:
        await get_or_create_user(session, callback.from_user)
        folders: list[FileFolder] = []
        folder_name: str | None = None
        parent_id: int | None = None
        if query is None:
            folders = await service.list_folders(session, callback.from_user.id, parent_id=folder_id)
            if folder_id is not None:
                folder = await service.get_folder(session, callback.from_user.id, folder_id)
                if folder is None:
                    await _set_current_folder(state, None)
                    folder_id = None
                    folders = await service.list_folders(session, callback.from_user.id, parent_id=None)
                else:
                    folder_name = folder.name
                    parent_id = folder.parent_id
        files, total = await service.list_files(
            session,
            callback.from_user.id,
            offset=offset,
            limit=PAGE_SIZE,
            query=query,
            folder_id=folder_id if query is None else None,
        )

    await callback.message.edit_text(
        _list_text(total, offset, folder_name=folder_name, query=query, folder_count=len(folders)),
        reply_markup=_list_markup(
            files,
            folders,
            total,
            offset,
            folder_id=folder_id,
            parent_id=parent_id,
            query=query,
        ),
    )


@router.callback_query(F.data == MENU_FILES)
async def open_files(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _set_current_folder(state, None)
    await callback.message.edit_text(
        "📁 <b>Файлы</b>\n\n"
        "Отправьте боту любой файл — и он сохранит его в текущую папку.\n"
        "Создавайте папки, смотрите список и остаток места.",
        reply_markup=_files_menu_kb(),
    )
    await callback.answer()


@router.message(F.document | F.photo | F.video | F.audio | F.voice)
async def store_incoming_file(message: Message, bot: Bot, state: FSMContext) -> None:
    meta = _extract_metadata(message)
    if meta is None:
        return
    file_name, mime_type, size, telegram_file_id, kind = meta
    settings = get_settings()
    folder_id = await _current_folder_id(state)

    async with session_scope() as session:
        await get_or_create_user(session, message.from_user)
        used, _, _, quota = await service.get_storage_stats(session, message.from_user.id)
        if quota is not None and used + size > quota:
            await message.answer(
                "⚠️ Недостаточно места в хранилище.\n"
                f"Занято: {_human_size(used)} из {_human_size(quota)}."
            )
            return

        stored = await service.save_file(
            session,
            message.from_user.id,
            file_name=file_name,
            mime_type=mime_type,
            size=size,
            telegram_file_id=telegram_file_id,
            kind=kind,
            storage_path=None,
            folder_id=folder_id,
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
                stored.storage_path = None
                downloaded = False

        file_id = stored.id

    text = (
        f"✅ Файл сохранён: <b>{html.escape(file_name)}</b>\n"
        f"Размер: {_human_size(size)}"
    )
    if folder_id is not None:
        text += "\n📂 Сохранён в текущую папку."
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


@router.callback_query(F.data.startswith("files:open:"))
async def open_folder(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":")[2]
    folder_id = None if raw == "root" else int(raw)
    if folder_id is not None:
        async with session_scope() as session:
            folder = await service.get_folder(session, callback.from_user.id, folder_id)
            if folder is None:
                await callback.answer("Папка не найдена.", show_alert=True)
                return
    await _set_current_folder(state, folder_id)
    await _render_list(callback, state, offset=0)
    await callback.answer()


@router.callback_query(F.data.startswith("files:list:"))
async def list_files_view(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    try:
        offset = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        offset = 0
    await _render_list(callback, state, offset=max(0, offset))
    await callback.answer()


@router.callback_query(F.data == "files:storage")
async def storage_view(callback: CallbackQuery) -> None:
    async with session_scope() as session:
        used, file_count, folder_count, quota = await service.get_storage_stats(
            session, callback.from_user.id
        )
    builder = InlineKeyboardBuilder()
    builder.button(text="📁 Файлы", callback_data=MENU_FILES)
    builder.button(text="⬅️ В меню", callback_data=MENU_HOME)
    builder.adjust(2)
    await callback.message.edit_text(
        _storage_text(used, file_count, folder_count, quota),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "files:mkdir")
async def mkdir_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FilesStates.creating_folder)
    await callback.message.edit_text(
        "📂 Введите имя новой папки.",
        reply_markup=back_home_kb(),
    )
    await callback.answer()


@router.message(StateFilter(FilesStates.creating_folder), F.text)
async def mkdir_apply(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("Имя папки не может быть пустым.", reply_markup=back_home_kb())
        return
    parent_id = await _current_folder_id(state)
    await state.set_state(None)

    async with session_scope() as session:
        await get_or_create_user(session, message.from_user)
        folder = await service.create_folder(
            session, message.from_user.id, name, parent_id=parent_id
        )
        folder_id = folder.id

    await _set_current_folder(state, folder_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Открыть папку", callback_data=f"files:open:{folder_id}")
    builder.button(text="📁 Файлы", callback_data=MENU_FILES)
    builder.adjust(1)
    await message.answer(
        f"✅ Папка <b>{html.escape(folder.name)}</b> создана.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("files:view:"))
async def view_file(callback: CallbackQuery, state: FSMContext) -> None:
    file_id = int(callback.data.split(":")[2])
    folder_id = await _current_folder_id(state)
    async with session_scope() as session:
        stored = await service.get_file(session, callback.from_user.id, file_id)
        if stored is None:
            await callback.answer("Файл не найден.", show_alert=True)
            return
        text = _detail_text(stored)
        stored_folder_id = stored.folder_id

    await callback.message.edit_text(
        text, reply_markup=_detail_markup(file_id, stored_folder_id or folder_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("files:get:"))
async def download_file(callback: CallbackQuery, bot: Bot) -> None:
    file_id = int(callback.data.split(":")[2])
    async with session_scope() as session:
        stored = await service.get_file(session, callback.from_user.id, file_id)
        if stored is None:
            await callback.answer("Файл не найден.", show_alert=True)
            return
        detached = StoredFile(
            id=stored.id,
            owner_id=stored.owner_id,
            file_name=stored.file_name,
            telegram_file_id=stored.telegram_file_id,
            kind=stored.kind,
            storage_path=stored.storage_path,
        )

    await _send_named_file(bot, callback.message.chat.id, detached)
    await callback.answer("Отправляю файл…")


@router.callback_query(F.data.startswith("files:del:"))
async def delete_file_view(callback: CallbackQuery, state: FSMContext) -> None:
    file_id = int(callback.data.split(":")[2])
    async with session_scope() as session:
        ok = await service.delete_file(session, callback.from_user.id, file_id)
        if not ok:
            await callback.answer("Файл не найден.", show_alert=True)
            return

    await _render_list(callback, state, offset=0)
    await callback.answer("Удалено")


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
    folder_id = await _current_folder_id(state)
    await state.set_state(None)

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
        reply_markup=_detail_markup(file_id, stored.folder_id or folder_id),
    )


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
    await state.set_state(None)

    async with session_scope() as session:
        await get_or_create_user(session, message.from_user)
        files, total = await service.list_files(
            session, message.from_user.id, offset=0, limit=PAGE_SIZE, query=query
        )

    await message.answer(
        _list_text(total, 0, query=query),
        reply_markup=_list_markup(files, [], total, 0, query=query),
    )

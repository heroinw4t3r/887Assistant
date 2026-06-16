"""FACEIT module — Telegram handlers.

CONTRACT:
  * Exposes ``router`` (aiogram Router, name="faceit").
  * Registers a handler for callback data ``MENU_FACEIT`` (app.bot.callbacks).
  * Uses callback prefix ``fc:`` for its own inline buttons.

Modes:
  * Single / multi check — user sends nicknames separated by spaces/newlines.
  * Bulk scan — every 3-letter (a-z, 17576) or 3-digit (0-9, 1000) combination,
    with a confirm gate, live progress, and a stop button.

The bulk scan runs in a background ``asyncio.Task`` so the "Остановить"
callback can still be processed by the dispatcher while the scan is in flight.
A module-level per-user state dict tracks the running flag and the stop flag.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import MENU_FACEIT, MENU_HOME
from app.bot.keyboards import back_home_kb
from app.config import get_settings
from app.db.base import session_scope
from app.modules.faceit.charset import count_digit, count_letter
from app.modules.faceit.client import FaceitClient
from app.modules.faceit.service import (
    bulk_scan,
    check_many,
    format_check_results,
    format_free_list,
)

logger = logging.getLogger("faceit")

router = Router(name="faceit")

# --- Callback data (prefix ``fc:``) -----------------------------------------
FC_SINGLE = "fc:single"
FC_BULK_LETTERS = "fc:bulk:letters"
FC_BULK_DIGITS = "fc:bulk:digits"
FC_RUN_LETTERS = "fc:run:letters"
FC_RUN_DIGITS = "fc:run:digits"
FC_STOP = "fc:stop"
FC_INFO = "fc:info"

# Cap on how many nicknames a single manual-check message may contain.
_SINGLE_CAP = 50

# Per-user bulk-scan state (keyed by Telegram user id).
_running: set[int] = set()
_stop_flags: dict[int, bool] = {}


class FaceitStates(StatesGroup):
    waiting_nicknames = State()


# --- Keyboards ---------------------------------------------------------------
def _menu_kb(*, has_key: bool):
    builder = InlineKeyboardBuilder()
    if has_key:
        builder.button(text="Проверить ники", callback_data=FC_SINGLE)
        builder.button(text="Все 3-буквенные (a-z)", callback_data=FC_BULK_LETTERS)
        builder.button(text="Все 3-значные (0-9)", callback_data=FC_BULK_DIGITS)
    builder.button(text="Про смену ника / IDLE", callback_data=FC_INFO)
    builder.button(text="В меню", callback_data=MENU_HOME)
    builder.adjust(1)
    return builder.as_markup()


def _confirm_kb(kind: str):
    run_cb = FC_RUN_LETTERS if kind == "letters" else FC_RUN_DIGITS
    builder = InlineKeyboardBuilder()
    builder.button(text="Запустить", callback_data=run_cb)
    builder.button(text="Назад", callback_data=MENU_FACEIT)
    builder.adjust(1)
    return builder.as_markup()


def _stop_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Остановить", callback_data=FC_STOP)
    return builder.as_markup()


# --- Menu --------------------------------------------------------------------
MENU_TEXT = (
    "<b>FACEIT — проверка никнеймов</b>\n\n"
    "Проверяю по официальному FACEIT Data API: занят ник или свободен.\n"
    "Поиск <b>чувствителен к регистру</b> (Nick != nick).\n\n"
    "Выберите действие:"
)

NO_KEY_TEXT = (
    "<b>FACEIT — проверка никнеймов</b>\n\n"
    "Ключ <code>FACEIT_API_KEY</code> не задан, проверка недоступна.\n"
    "Получите server-side ключ на <b>developers.faceit.com</b> "
    "(App Studio -> API Keys) и добавьте его в окружение бота.\n\n"
    "Раздел «Про смену ника / IDLE» доступен и без ключа."
)


@router.callback_query(F.data == MENU_FACEIT)
async def open_faceit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    settings = get_settings()
    has_key = bool(settings.faceit_api_key)
    text = MENU_TEXT if has_key else NO_KEY_TEXT
    await callback.message.edit_text(text, reply_markup=_menu_kb(has_key=has_key))
    await callback.answer()


# --- Single / multi check ----------------------------------------------------
SINGLE_PROMPT = (
    "Пришлите один или несколько ников (через пробел или с новой строки).\n"
    f"За раз проверю до <b>{_SINGLE_CAP}</b> ников.\n\n"
    "Регистр важен: <code>Foo</code> и <code>foo</code> — разные ники."
)


@router.callback_query(F.data == FC_SINGLE)
async def ask_nicknames(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FaceitStates.waiting_nicknames)
    await callback.message.edit_text(SINGLE_PROMPT, reply_markup=back_home_kb())
    await callback.answer()


@router.message(FaceitStates.waiting_nicknames, F.text)
async def receive_nicknames(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    if not settings.faceit_api_key:
        await state.clear()
        await message.answer("Ключ FACEIT_API_KEY не задан.", reply_markup=back_home_kb())
        return

    # Split on any whitespace, drop empties, dedupe preserving order.
    raw = message.text.split()
    seen: set[str] = set()
    nicknames: list[str] = []
    for nick in raw:
        if nick not in seen:
            seen.add(nick)
            nicknames.append(nick)

    if not nicknames:
        await message.answer("Не вижу ников. Пришлите хотя бы один.")
        return

    note = ""
    if len(nicknames) > _SINGLE_CAP:
        note = f"\n\nПрислано больше {_SINGLE_CAP}, проверю только первые {_SINGLE_CAP}."
        nicknames = nicknames[:_SINGLE_CAP]

    await state.clear()
    status_msg = await message.answer(f"Проверяю {len(nicknames)} ник(ов)…")

    client = FaceitClient(
        settings.faceit_api_key,
        rps=settings.faceit_rate_limit_rps,
        cache_ttl=settings.faceit_cache_ttl,
    )
    try:
        async with session_scope() as session:
            results = await check_many(client, nicknames, session=session)
    finally:
        await client.aclose()

    text = format_check_results(results) + note
    await _safe_edit(status_msg, text, reply_markup=back_home_kb())


# --- Bulk scan ---------------------------------------------------------------
def _bulk_warning(kind: str) -> str:
    settings = get_settings()
    rps = settings.faceit_rate_limit_rps or 1.0
    total = count_letter(3) if kind == "letters" else count_digit(3)
    label = "3-буквенных (a–z)" if kind == "letters" else "3-значных (0–9)"
    est_seconds = int(total / rps) if rps > 0 else 0
    minutes = est_seconds // 60
    return (
        f"<b>Массовая проверка {label} ников</b>\n\n"
        f"Всего комбинаций: <b>{total}</b>.\n"
        f"При лимите ~{rps:g} запр./сек это займёт примерно <b>{minutes} мин</b> "
        f"(≈{est_seconds} сек).\n\n"
        "Можно остановить в любой момент — покажу найденное на этот момент.\n"
        "Запустить?"
    )


@router.callback_query(F.data.in_({FC_BULK_LETTERS, FC_BULK_DIGITS}))
async def confirm_bulk(callback: CallbackQuery) -> None:
    settings = get_settings()
    if not settings.faceit_api_key:
        await callback.answer("Ключ FACEIT_API_KEY не задан.", show_alert=True)
        return
    kind = "letters" if callback.data == FC_BULK_LETTERS else "digits"
    await callback.message.edit_text(_bulk_warning(kind), reply_markup=_confirm_kb(kind))
    await callback.answer()


@router.callback_query(F.data.in_({FC_RUN_LETTERS, FC_RUN_DIGITS}))
async def run_bulk(callback: CallbackQuery) -> None:
    settings = get_settings()
    if not settings.faceit_api_key:
        await callback.answer("Ключ FACEIT_API_KEY не задан.", show_alert=True)
        return

    user_id = callback.from_user.id
    if user_id in _running:
        await callback.answer("Проверка уже идёт.", show_alert=True)
        return

    kind = "letters" if callback.data == FC_RUN_LETTERS else "digits"
    _running.add(user_id)
    _stop_flags[user_id] = False

    await callback.message.edit_text("Запускаю проверку…", reply_markup=_stop_kb())
    await callback.answer()

    # Run the scan detached so the dispatcher can still handle the stop button.
    asyncio.create_task(_scan_task(callback.message, user_id, kind))


@router.callback_query(F.data == FC_STOP)
async def stop_bulk(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    if user_id in _running:
        _stop_flags[user_id] = True
        await callback.answer("Останавливаю…")
    else:
        await callback.answer("Нет активной проверки.")


async def _scan_task(message: Message, user_id: int, kind: str) -> None:
    settings = get_settings()
    total = count_letter(3) if kind == "letters" else count_digit(3)

    client = FaceitClient(
        settings.faceit_api_key,
        rps=settings.faceit_rate_limit_rps,
        cache_ttl=settings.faceit_cache_ttl,
    )

    async def on_progress(done: int, total_: int, free_count: int) -> None:
        pct = int(done / total_ * 100) if total_ else 100
        await _safe_edit(
            message,
            f"Проверка… {done}/{total_} ({pct}%)\n"
            f"Свободных найдено: <b>{free_count}</b>",
            reply_markup=_stop_kb(),
        )

    def should_stop() -> bool:
        return _stop_flags.get(user_id, False)

    try:
        async with session_scope() as session:
            results = await bulk_scan(
                client,
                kind,
                on_progress=on_progress,
                should_stop=should_stop,
                length=3,
                session=session,
            )
        stopped = should_stop()
        done = len(results)
        head = (
            f"Остановлено на {done}/{total}.\n\n"
            if stopped
            else f"Готово: проверено {done}/{total}.\n\n"
        )
        chunks = format_free_list(results)
        await _safe_edit(message, head + chunks[0], reply_markup=back_home_kb())
        for chunk in chunks[1:]:
            await message.answer(chunk)
    except Exception:  # noqa: BLE001 - never leave the user hanging on a crash
        logger.exception("FACEIT bulk scan failed (user=%s, kind=%s)", user_id, kind)
        await _safe_edit(
            message,
            "Во время проверки произошла ошибка. Попробуйте позже.",
            reply_markup=back_home_kb(),
        )
    finally:
        await client.aclose()
        _running.discard(user_id)
        _stop_flags.pop(user_id, None)


# --- Info screen -------------------------------------------------------------
INFO_TEXT = (
    "<b>Смена ника и «IDLE»-захват на FACEIT</b>\n\n"
    "<b>Сменить свой ник:</b>\n"
    "• FACEIT Premium — 1 бесплатная смена раз в 3 месяца.\n"
    "• Без Premium — нужно купить предмет «Nickname Change» в FACEIT Shop.\n\n"
    "<b>Захват «простаивающего» ника (Idle Nickname Claim):</b>\n"
    "Ник можно запросить, только если аккаунт-владелец соответствует <i>всем</i> условиям:\n"
    "• не заходил больше 12 месяцев и без долгосрочных банов;\n"
    "• нет активной подписки;\n"
    "• не verified;\n"
    "• не удалён/деактивирован;\n"
    "• ник не оскорбительный и не занят в вариантах с другим регистром.\n\n"
    "Неактивным шлют письмо за 7 дней; любой вход сбрасывает таймер 12 месяцев. "
    "При захвате прежний владелец получает обезличенный ник (напр. yellow1234), "
    "1000 FACEIT Points и одну бесплатную смену.\n"
    "Захват стоит перк Premium либо ~$4.99 / 5000 FACEIT Points и делается через "
    "Shop / Account Settings (НЕ при обычной регистрации).\n"
    "Ники <b>удалённых</b> аккаунтов не освобождаются никогда.\n\n"
    "<b>Честно о точности:</b> Data API достоверно сообщает только «занят/свободен». "
    "Будет ли занятый ник «idle-claimable», по этому эндпоинту точно определить нельзя — "
    "это лишь эвристическая оценка по последней активности, а не гарантия."
)


@router.callback_query(F.data == FC_INFO)
async def show_info(callback: CallbackQuery) -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=MENU_FACEIT)
    await callback.message.edit_text(INFO_TEXT, reply_markup=builder.as_markup())
    await callback.answer()


async def _safe_edit(message: Message, text: str, *, reply_markup=None) -> None:
    """Edit a message, swallowing Telegram errors (e.g. identical text / flood)."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception as exc:  # noqa: BLE001 - progress edits are best-effort
        logger.debug("FACEIT edit_text skipped: %s", exc)

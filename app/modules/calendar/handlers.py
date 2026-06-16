"""Calendar module — Telegram handlers.

CONTRACT:
  * Exposes ``router`` (aiogram Router).
  * Registers a handler for callback data ``MENU_CALENDAR`` (app.bot.callbacks).
  * Uses callback prefix ``cal:`` for its own inline buttons.

Callback grammar (prefix ``cal:``):
  cal:month:<year>:<month>   month grid navigation
  cal:day:<yyyy-mm-dd>       day view
  cal:ev:<id>                event details
  cal:add:<yyyy-mm-dd>       start the add-event FSM for that day
  cal:del:<id>               delete an event
  cal:rem:<minutes|none>     reminder choice during the add FSM
  cal:allday                 (text shortcut "весь день" also works)
  cal:sync                   subscription URLs + instructions
  cal:today                  jump to today's day view
  cal:noop                   inert padding / weekday-header buttons
"""
from __future__ import annotations

import calendar as _calendar
from datetime import UTC, date, datetime
from html import escape
from urllib.parse import urlsplit

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.callbacks import MENU_CALENDAR, MENU_HOME
from app.config import get_settings
from app.db.base import session_scope
from app.db.models import User
from app.db.repository import get_or_create_user
from app.modules.calendar import service
from app.modules.calendar.service import ensure_utc, resolve_tz

router = Router(name="calendar")

MONTHS_NOM = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_FULL = [
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье",
]

REMINDER_CHOICES: list[tuple[str, str]] = [
    ("нет", "none"),
    ("10м", "10"),
    ("30м", "30"),
    ("1ч", "60"),
    ("1 день", "1440"),
]
REMINDER_LABELS = {
    10: "за 10 минут",
    30: "за 30 минут",
    60: "за час",
    1440: "за день",
}


def _reminder_label(minutes: int) -> str:
    return REMINDER_LABELS.get(minutes, f"{minutes}м")


class AddEvent(StatesGroup):
    title = State()
    description = State()
    time = State()
    reminder = State()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _ensure_user(tg_user) -> User:
    async with session_scope() as session:
        return await get_or_create_user(session, tg_user)


def _fmt_day_title(day: date) -> str:
    weekday = WEEKDAYS_FULL[day.weekday()]
    return f"{weekday}, {day.day} {MONTHS_GEN[day.month - 1]} {day.year}"


def _event_line(event, tz) -> str:
    if event.all_day:
        prefix = "весь день"
    else:
        prefix = ensure_utc(event.start_at).astimezone(tz).strftime("%H:%M")
    return f"{prefix} — {escape(event.title)}"


def _build_month_kb(
    year: int, month: int, event_days: set[int]
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    # Header: ◀  <Month Year>  ▶
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    rows.append(
        [
            InlineKeyboardButton(text="◀", callback_data=f"cal:month:{prev_year}:{prev_month}"),
            InlineKeyboardButton(
                text=f"{MONTHS_NOM[month - 1]} {year}", callback_data="cal:noop"
            ),
            InlineKeyboardButton(text="▶", callback_data=f"cal:month:{next_year}:{next_month}"),
        ]
    )

    # Weekday header.
    rows.append(
        [InlineKeyboardButton(text=name, callback_data="cal:noop") for name in WEEKDAYS_SHORT]
    )

    # Day grid (Monday-first weeks).
    for week in _calendar.monthcalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day_num in week:
            if day_num == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="cal:noop"))
                continue
            label = f"•{day_num}" if day_num in event_days else str(day_num)
            iso = f"{year:04d}-{month:02d}-{day_num:02d}"
            row.append(InlineKeyboardButton(text=label, callback_data=f"cal:day:{iso}"))
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(text="📲 Синхронизация", callback_data="cal:sync"),
            InlineKeyboardButton(text="Сегодня", callback_data="cal:today"),
        ]
    )
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=MENU_HOME)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_month(
    owner_id: int, tz: str, year: int, month: int
) -> tuple[str, InlineKeyboardMarkup]:
    zone = resolve_tz(tz)
    async with session_scope() as session:
        events = await service.list_events_in_month(session, owner_id, year, month, tz)
    event_days = {ensure_utc(ev.start_at).astimezone(zone).day for ev in events}
    text = (
        f"📅 <b>{MONTHS_NOM[month - 1]} {year}</b>\n\n"
        "Выберите день. Точкой отмечены дни с событиями."
    )
    return text, _build_month_kb(year, month, event_days)


async def _render_day(owner_id: int, tz: str, day: date) -> tuple[str, InlineKeyboardMarkup]:
    zone = resolve_tz(tz)
    async with session_scope() as session:
        events = await service.list_events_for_day(session, owner_id, day, tz)

    lines = [f"📅 <b>{_fmt_day_title(day)}</b>", ""]
    if events:
        for ev in events:
            lines.append(f"• {_event_line(ev, zone)}")
    else:
        lines.append("Событий нет.")
    text = "\n".join(lines)

    rows: list[list[InlineKeyboardButton]] = []
    for ev in events:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📌 {_event_line(ev, zone)}", callback_data=f"cal:ev:{ev.id}"
                )
            ]
        )
    iso = day.isoformat()
    rows.append([InlineKeyboardButton(text="➕ Добавить событие", callback_data=f"cal:add:{iso}")])
    rows.append(
        [InlineKeyboardButton(text="◀ Месяц", callback_data=f"cal:month:{day.year}:{day.month}")]
    )
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=MENU_HOME)])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _render_event(event, tz: str) -> tuple[str, InlineKeyboardMarkup]:
    zone = resolve_tz(tz)
    local = ensure_utc(event.start_at).astimezone(zone)
    lines = [f"📌 <b>{escape(event.title)}</b>", ""]
    if event.all_day:
        lines.append(f"🗓 {_fmt_day_title(local.date())} · весь день")
    else:
        lines.append(f"🗓 {_fmt_day_title(local.date())}")
        lines.append(f"🕒 {local.strftime('%H:%M')}")
    if event.reminder_minutes is not None:
        lines.append(f"🔔 Напоминание {_reminder_label(event.reminder_minutes)}")
    if event.description:
        lines.append("")
        lines.append(escape(event.description))
    text = "\n".join(lines)

    iso = local.date().isoformat()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"cal:del:{event.id}")],
            [InlineKeyboardButton(text="◀ День", callback_data=f"cal:day:{iso}")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data=MENU_HOME)],
        ]
    )
    return text, kb


def _reminder_kb() -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(text=label, callback_data=f"cal:rem:{value}")
        for label, value in REMINDER_CHOICES
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


# --------------------------------------------------------------------------- #
# Month / navigation
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == MENU_CALENDAR)
async def open_calendar(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user = await _ensure_user(callback.from_user)
    today = datetime.now(resolve_tz(user.timezone)).date()
    text, kb = await _render_month(user.id, user.timezone, today.year, today.month)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("cal:month:"))
async def show_month(callback: CallbackQuery) -> None:
    _, _, year_s, month_s = callback.data.split(":")
    user = await _ensure_user(callback.from_user)
    text, kb = await _render_month(user.id, user.timezone, int(year_s), int(month_s))
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "cal:noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "cal:today")
async def show_today(callback: CallbackQuery) -> None:
    user = await _ensure_user(callback.from_user)
    today = datetime.now(resolve_tz(user.timezone)).date()
    text, kb = await _render_day(user.id, user.timezone, today)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# --------------------------------------------------------------------------- #
# Day / event views
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("cal:day:"))
async def show_day(callback: CallbackQuery) -> None:
    iso = callback.data.split(":", 2)[2]
    user = await _ensure_user(callback.from_user)
    day = date.fromisoformat(iso)
    text, kb = await _render_day(user.id, user.timezone, day)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("cal:ev:"))
async def show_event(callback: CallbackQuery) -> None:
    event_id = int(callback.data.split(":")[2])
    user = await _ensure_user(callback.from_user)
    async with session_scope() as session:
        event = await service.get_event(session, user.id, event_id)
    if event is None:
        await callback.answer("Событие не найдено", show_alert=True)
        return
    text, kb = _render_event(event, user.timezone)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("cal:del:"))
async def delete_event(callback: CallbackQuery) -> None:
    event_id = int(callback.data.split(":")[2])
    user = await _ensure_user(callback.from_user)
    async with session_scope() as session:
        event = await service.get_event(session, user.id, event_id)
        day = (
            ensure_utc(event.start_at).astimezone(resolve_tz(user.timezone)).date()
            if event
            else None
        )
        deleted = await service.delete_event(session, user.id, event_id)
    if not deleted or day is None:
        await callback.answer("Событие не найдено", show_alert=True)
        return
    text, kb = await _render_day(user.id, user.timezone, day)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("Событие удалено")


# --------------------------------------------------------------------------- #
# Sync instructions
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "cal:sync")
async def show_sync(callback: CallbackQuery) -> None:
    user = await _ensure_user(callback.from_user)
    settings = get_settings()
    base = settings.base_url.rstrip("/")
    https_url = f"{base}/calendar/{user.calendar_token}.ics"
    parts = urlsplit(base)
    webcal_url = f"webcal://{parts.netloc}{parts.path}/calendar/{user.calendar_token}.ics"

    text = (
        "📲 <b>Синхронизация календаря с телефоном</b>\n\n"
        "Подпишитесь на персональную ленту в формате <b>.ics</b>/<b>webcal</b>:\n\n"
        f"<code>{escape(https_url)}</code>\n\n"
        f"<code>{escape(webcal_url)}</code>\n\n"
        "<b>Google Календарь:</b> Другие календари → Подписаться по URL → вставьте ссылку.\n"
        "<b>Apple/iOS:</b> Настройки → Календарь → Учётные записи → "
        "Добавить учётную запись → Другое → Подписной календарь.\n\n"
        "⚠️ Это <b>одностороннняя</b> синхронизация, только для чтения: события появляются "
        "на телефоне, но изменить их там нельзя. Телефон обновляет ленту не сразу "
        "(интервал может составлять несколько часов)."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀ Календарь", callback_data=MENU_CALENDAR)],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data=MENU_HOME)],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    await callback.answer()


# --------------------------------------------------------------------------- #
# Add-event FSM
# --------------------------------------------------------------------------- #
def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✖️ Отмена", callback_data=MENU_CALENDAR)]]
    )


@router.callback_query(F.data.startswith("cal:add:"))
async def add_start(callback: CallbackQuery, state: FSMContext) -> None:
    iso = callback.data.split(":", 2)[2]
    await state.clear()
    await state.update_data(day=iso)
    await state.set_state(AddEvent.title)
    await callback.message.edit_text(
        f"➕ <b>Новое событие на {escape(iso)}</b>\n\nВведите название события:",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(AddEvent.title)
async def add_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым. Попробуйте ещё раз:")
        return
    await state.update_data(title=title)
    await state.set_state(AddEvent.description)
    await message.answer(
        "Введите описание события или отправьте <b>-</b>, чтобы пропустить:"
    )


@router.message(AddEvent.description)
async def add_description(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    description = None if text in ("", "-") else text
    await state.update_data(description=description)
    await state.set_state(AddEvent.time)
    await message.answer(
        "Введите время в формате <b>ЧЧ:ММ</b> (например, 14:30)\n"
        "или отправьте <b>весь день</b>, если событие на весь день:"
    )


def _parse_time(text: str) -> tuple[bool, tuple[int, int] | None]:
    """Return (all_day, (hour, minute) | None). Raises ValueError on bad input."""
    normalized = text.strip().lower()
    if normalized in ("весь день", "all day", "-"):
        return True, None
    raw = normalized.replace(".", ":").replace(" ", "")
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError("bad time")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("out of range")
    return False, (hour, minute)


@router.message(AddEvent.time)
async def add_time(message: Message, state: FSMContext) -> None:
    try:
        all_day, hm = _parse_time(message.text or "")
    except ValueError:
        await message.answer(
            "Не понял время. Введите в формате <b>ЧЧ:ММ</b> или <b>весь день</b>:"
        )
        return
    await state.update_data(
        all_day=all_day,
        hour=None if hm is None else hm[0],
        minute=None if hm is None else hm[1],
    )
    await state.set_state(AddEvent.reminder)
    await message.answer("Напомнить о событии?", reply_markup=_reminder_kb())


@router.callback_query(AddEvent.reminder, F.data.startswith("cal:rem:"))
async def add_reminder(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":")[2]
    reminder_minutes = None if value == "none" else int(value)

    data = await state.get_data()
    await state.clear()

    user = await _ensure_user(callback.from_user)
    zone = resolve_tz(user.timezone)
    day = date.fromisoformat(data["day"])
    all_day = bool(data.get("all_day"))
    if all_day:
        local_start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=zone)
    else:
        local_start = datetime(
            day.year, day.month, day.day, data["hour"], data["minute"], tzinfo=zone
        )
    start_utc = local_start.astimezone(UTC)

    async with session_scope() as session:
        await service.create_event(
            session,
            user.id,
            title=data["title"],
            start_at=start_utc,
            description=data.get("description"),
            all_day=all_day,
            reminder_minutes=reminder_minutes,
        )

    when = "весь день" if all_day else local_start.strftime("%H:%M")
    confirm = (
        "✅ <b>Событие создано</b>\n\n"
        f"<b>{escape(data['title'])}</b>\n"
        f"🗓 {_fmt_day_title(day)} · {when}"
    )
    if reminder_minutes is not None:
        confirm += f"\n🔔 Напоминание {_reminder_label(reminder_minutes)}"

    text, kb = await _render_day(user.id, user.timezone, day)
    await callback.message.edit_text(confirm)
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer("Готово")

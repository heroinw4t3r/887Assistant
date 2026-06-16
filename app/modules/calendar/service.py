"""Calendar service layer — all DB logic, takes an AsyncSession.

Every datetime is stored in UTC (timezone-aware). The service translates between
the user's local timezone (an IANA name like ``Europe/Moscow``) and UTC when
computing day/month ranges, but never persists naive datetimes.
"""
from __future__ import annotations

import calendar as _calendar
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CalendarEvent


def resolve_tz(tz: str | None) -> ZoneInfo:
    """Return a ZoneInfo for ``tz``, falling back to UTC if it is invalid."""
    if not tz:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def _day_bounds_utc(day: date, tz: str) -> tuple[datetime, datetime]:
    """Return [start, end) UTC datetimes for the local calendar ``day`` in ``tz``."""
    zone = resolve_tz(tz)
    local_start = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=zone)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def _month_bounds_utc(year: int, month: int, tz: str) -> tuple[datetime, datetime]:
    """Return [start, end) UTC datetimes spanning the local ``year``/``month``."""
    zone = resolve_tz(tz)
    local_start = datetime(year, month, 1, 0, 0, 0, tzinfo=zone)
    last_day = _calendar.monthrange(year, month)[1]
    local_end = datetime(year, month, last_day, 0, 0, 0, tzinfo=zone) + timedelta(days=1)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Coerce a datetime to a timezone-aware UTC datetime.

    Datetimes are always persisted in UTC, but some backends (notably SQLite)
    return naive values on read; we treat such naive values as UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# Backwards-compatible private alias used throughout this module.
_to_utc = ensure_utc


async def create_event(
    session: AsyncSession,
    owner_id: int,
    *,
    title: str,
    start_at: datetime,
    end_at: datetime | None = None,
    description: str | None = None,
    all_day: bool = False,
    reminder_minutes: int | None = None,
) -> CalendarEvent:
    event = CalendarEvent(
        owner_id=owner_id,
        title=title,
        description=description,
        start_at=_to_utc(start_at),
        end_at=_to_utc(end_at) if end_at is not None else None,
        all_day=all_day,
        reminder_minutes=reminder_minutes,
    )
    session.add(event)
    await session.flush()
    return event


async def list_events_for_day(
    session: AsyncSession, owner_id: int, day: date, tz: str
) -> list[CalendarEvent]:
    start_utc, end_utc = _day_bounds_utc(day, tz)
    result = await session.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.owner_id == owner_id,
            CalendarEvent.start_at >= start_utc,
            CalendarEvent.start_at < end_utc,
        )
        .order_by(CalendarEvent.start_at)
    )
    return list(result.scalars().all())


async def list_events_in_month(
    session: AsyncSession, owner_id: int, year: int, month: int, tz: str
) -> list[CalendarEvent]:
    start_utc, end_utc = _month_bounds_utc(year, month, tz)
    result = await session.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.owner_id == owner_id,
            CalendarEvent.start_at >= start_utc,
            CalendarEvent.start_at < end_utc,
        )
        .order_by(CalendarEvent.start_at)
    )
    return list(result.scalars().all())


async def get_event(
    session: AsyncSession, owner_id: int, event_id: int
) -> CalendarEvent | None:
    result = await session.execute(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.owner_id == owner_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_event(session: AsyncSession, owner_id: int, event_id: int) -> bool:
    event = await get_event(session, owner_id, event_id)
    if event is None:
        return False
    await session.delete(event)
    await session.flush()
    return True


async def update_event(
    session: AsyncSession,
    owner_id: int,
    event_id: int,
    *,
    title: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    description: str | None = None,
    all_day: bool | None = None,
    reminder_minutes: int | None = None,
) -> CalendarEvent | None:
    """Owner-scoped partial update. Only provided (non-None) fields are changed.

    Resetting a reminder is also possible because changing the time clears the
    ``reminder_sent`` flag so a rescheduled event can fire again.
    """
    event = await get_event(session, owner_id, event_id)
    if event is None:
        return None
    if title is not None:
        event.title = title
    if description is not None:
        event.description = description
    if start_at is not None:
        event.start_at = _to_utc(start_at)
        event.reminder_sent = False
    if end_at is not None:
        event.end_at = _to_utc(end_at)
    if all_day is not None:
        event.all_day = all_day
    if reminder_minutes is not None:
        event.reminder_minutes = reminder_minutes
        event.reminder_sent = False
    await session.flush()
    return event


async def list_all_events(session: AsyncSession, owner_id: int) -> list[CalendarEvent]:
    result = await session.execute(
        select(CalendarEvent)
        .where(CalendarEvent.owner_id == owner_id)
        .order_by(CalendarEvent.start_at)
    )
    return list(result.scalars().all())


async def due_reminders(session: AsyncSession, now_utc: datetime) -> list[CalendarEvent]:
    """Events whose reminder window is open: reminder set, not yet sent, and
    ``start_at - reminder_minutes <= now_utc <= start_at``.

    The minute arithmetic is done in Python (rather than SQL) so the logic is
    backend-agnostic and easy to reason about.
    """
    now_utc = _to_utc(now_utc)
    result = await session.execute(
        select(CalendarEvent).where(
            CalendarEvent.reminder_minutes.is_not(None),
            CalendarEvent.reminder_sent.is_(False),
            CalendarEvent.start_at >= now_utc,
        )
    )
    due: list[CalendarEvent] = []
    for event in result.scalars().all():
        # SQLite returns naive datetimes even for tz-aware columns; normalise.
        start = _to_utc(event.start_at)
        trigger = start - timedelta(minutes=event.reminder_minutes or 0)
        if trigger <= now_utc <= start:
            due.append(event)
    return due


async def mark_reminder_sent(session: AsyncSession, event_id: int) -> None:
    event = await session.get(CalendarEvent, event_id)
    if event is not None:
        event.reminder_sent = True
        await session.flush()

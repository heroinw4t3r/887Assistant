"""Calendar module tests — isolated in-memory async SQLite, no network."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import User
from app.modules.calendar import service
from app.modules.calendar.ics import build_ics_for_events

MOSCOW = "Europe/Moscow"
USER_ID = 1001


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(User(id=USER_ID, timezone=MOSCOW, calendar_token="tok-test"))
        await session.commit()
    try:
        yield maker
    finally:
        await engine.dispose()


async def test_create_and_list_for_day_timezone_boundary(session_factory):
    # Moscow is UTC+3. 23:30 on the 15th (MSK) is 20:30 UTC the same day.
    late = datetime(2026, 1, 15, 23, 30, tzinfo=ZoneInfo(MOSCOW)).astimezone(UTC)
    # 00:30 on the 16th (MSK) is 21:30 UTC on the 15th — must land on the 16th locally.
    early_next = datetime(2026, 1, 16, 0, 30, tzinfo=ZoneInfo(MOSCOW)).astimezone(UTC)

    async with session_factory() as session:
        await service.create_event(session, USER_ID, title="Late MSK", start_at=late)
        await service.create_event(session, USER_ID, title="Next day MSK", start_at=early_next)
        await session.commit()

    async with session_factory() as session:
        day15 = await service.list_events_for_day(
            session, USER_ID, date(2026, 1, 15), MOSCOW
        )
        day16 = await service.list_events_for_day(
            session, USER_ID, date(2026, 1, 16), MOSCOW
        )

    assert [e.title for e in day15] == ["Late MSK"]
    assert [e.title for e in day16] == ["Next day MSK"]


async def test_list_for_day_orders_by_start(session_factory):
    base = datetime(2026, 3, 10, 9, 0, tzinfo=ZoneInfo(MOSCOW)).astimezone(UTC)
    async with session_factory() as session:
        await service.create_event(
            session, USER_ID, title="Second", start_at=base + timedelta(hours=2)
        )
        await service.create_event(session, USER_ID, title="First", start_at=base)
        await session.commit()

    async with session_factory() as session:
        events = await service.list_events_for_day(
            session, USER_ID, date(2026, 3, 10), MOSCOW
        )
    assert [e.title for e in events] == ["First", "Second"]


async def test_invalid_timezone_falls_back_to_utc():
    assert service.resolve_tz("Not/AZone").key == "UTC"
    assert service.resolve_tz(None).key == "UTC"


async def test_due_reminders(session_factory):
    now = datetime.now(UTC)
    async with session_factory() as session:
        # Window open: starts in 5 min, reminder 10 min before.
        await service.create_event(
            session,
            USER_ID,
            title="Soon",
            start_at=now + timedelta(minutes=5),
            reminder_minutes=10,
        )
        # Too far out: starts in 2h, reminder 10 min before -> not due yet.
        await service.create_event(
            session,
            USER_ID,
            title="Later",
            start_at=now + timedelta(hours=2),
            reminder_minutes=10,
        )
        await session.commit()

    async with session_factory() as session:
        due = await service.due_reminders(session, now)
        assert [e.title for e in due] == ["Soon"]
        await service.mark_reminder_sent(session, due[0].id)
        await session.commit()

    async with session_factory() as session:
        due_again = await service.due_reminders(session, now)
        assert due_again == []


async def test_ics_contains_event_summary(session_factory):
    start = datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo(MOSCOW)).astimezone(UTC)
    async with session_factory() as session:
        await service.create_event(
            session,
            USER_ID,
            title="Standup Meeting",
            start_at=start,
            description="Daily sync",
            reminder_minutes=30,
        )
        await session.commit()

    async with session_factory() as session:
        user = await session.get(User, USER_ID)
        events = await service.list_all_events(session, USER_ID)
        data = build_ics_for_events(events, user)

    text = data.decode("utf-8")
    assert "BEGIN:VCALENDAR" in text
    assert "887Assistant" in text
    assert "Standup Meeting" in text
    assert "BEGIN:VALARM" in text
    assert "-PT30M" in text


async def test_ics_all_day_uses_date_value(session_factory):
    start = datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo(MOSCOW)).astimezone(UTC)
    async with session_factory() as session:
        await service.create_event(
            session, USER_ID, title="Holiday", start_at=start, all_day=True
        )
        await session.commit()

    async with session_factory() as session:
        user = await session.get(User, USER_ID)
        events = await service.list_all_events(session, USER_ID)
        data = build_ics_for_events(events, user)

    text = data.decode("utf-8")
    assert "Holiday" in text
    assert "DTSTART;VALUE=DATE:" in text

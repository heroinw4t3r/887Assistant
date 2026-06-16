"""iCalendar (.ics) feed generation.

CONTRACT (consumed by app.web.server):
    async def build_ics_for_token(token: str) -> bytes | None
        Return the full VCALENDAR bytes for the user owning ``token``,
        or None if the token is unknown.

``build_ics_for_events`` is a synchronous helper that turns a list of
``CalendarEvent`` rows into VCALENDAR bytes; it is what ``build_ics_for_token``
uses internally and what the tests exercise directly (no DB / network needed).
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from icalendar import Alarm, Calendar, Event

from app.db.base import session_scope
from app.db.models import CalendarEvent, User
from app.db.repository import get_user_by_calendar_token
from app.modules.calendar.service import ensure_utc

CALENDAR_NAME = "887Assistant"
PRODID = "-//887Assistant//Calendar//EN"


def build_ics_for_events(events: Iterable[CalendarEvent], user: User) -> bytes:
    """Build VCALENDAR bytes for ``events`` belonging to ``user``."""
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", CALENDAR_NAME)

    for event in events:
        vevent = Event()
        vevent.add("uid", event.uid)
        vevent.add("summary", event.title)
        if event.description:
            vevent.add("description", event.description)

        start = ensure_utc(event.start_at)
        if event.all_day:
            # All-day events use DATE (not DATE-TIME) values.
            vevent.add("dtstart", start.date())
            end = ensure_utc(event.end_at) if event.end_at else start
            vevent.add("dtend", (end + timedelta(days=1)).date())
        else:
            vevent.add("dtstart", start)
            if event.end_at:
                vevent.add("dtend", ensure_utc(event.end_at))

        if event.reminder_minutes is not None:
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", event.title)
            alarm.add("trigger", timedelta(minutes=-event.reminder_minutes))
            vevent.add_component(alarm)

        cal.add_component(vevent)

    return cal.to_ical()


async def build_ics_for_token(token: str) -> bytes | None:
    async with session_scope() as session:
        user = await get_user_by_calendar_token(session, token)
        if user is None:
            return None
        # Import here to avoid a circular import at module load time.
        from app.modules.calendar.service import list_all_events

        events = await list_all_events(session, user.id)
        return build_ics_for_events(events, user)

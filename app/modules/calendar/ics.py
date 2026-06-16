"""iCalendar (.ics) feed generation.

CONTRACT (consumed by app.web.server):
    async def build_ics_for_token(token: str) -> bytes | None
        Return the full VCALENDAR bytes for the user owning ``token``,
        or None if the token is unknown.

TODO(subagent-2): build a real VCALENDAR from the user's events.
"""
from __future__ import annotations

from app.db.base import session_scope
from app.db.repository import get_user_by_calendar_token


async def build_ics_for_token(token: str) -> bytes | None:
    async with session_scope() as session:
        user = await get_user_by_calendar_token(session, token)
        if user is None:
            return None
    # Minimal empty-but-valid calendar until subagent-2 fills in events.
    return (
        b"BEGIN:VCALENDAR\r\n"
        b"VERSION:2.0\r\n"
        b"PRODID:-//887Assistant//EN\r\n"
        b"END:VCALENDAR\r\n"
    )

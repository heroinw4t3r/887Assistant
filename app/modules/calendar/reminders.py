"""Event reminder scheduling.

CONTRACT (consumed by app.main):
    def register_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> None
        Register the periodic job that delivers due event reminders.

A single interval job runs every 60 seconds, scans for events whose reminder
window is open, sends a Telegram message to the owner, and marks the reminder as
sent. Sends are individually guarded so one failure never breaks the batch and
the job never raises out into the scheduler.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.base import session_scope
from app.db.models import User
from app.modules.calendar.service import (
    due_reminders,
    ensure_utc,
    mark_reminder_sent,
    resolve_tz,
)

logger = logging.getLogger("calendar.reminders")

REMINDER_JOB_ID = "calendar_reminders"


def _format_reminder(event, tz: ZoneInfo) -> str:
    local_start = ensure_utc(event.start_at).astimezone(tz)
    when = "весь день" if event.all_day else local_start.strftime("%H:%M")
    lines = [
        "🔔 <b>Напоминание о событии</b>",
        "",
        f"<b>{escape(event.title)}</b>",
        f"🕒 {local_start.strftime('%d.%m.%Y')} · {when}",
    ]
    if event.description:
        lines.append("")
        lines.append(escape(event.description))
    return "\n".join(lines)


async def _dispatch_due_reminders(bot: Bot) -> None:
    async with session_scope() as session:
        events = await due_reminders(session, datetime.now(UTC))
        for event in events:
            owner = await session.get(User, event.owner_id)
            tz = resolve_tz(owner.timezone if owner else None)
            try:
                await bot.send_message(event.owner_id, _format_reminder(event, tz))
            except Exception:  # noqa: BLE001 — never let one send break the batch
                logger.exception(
                    "Failed to send reminder for event %s to %s",
                    event.id,
                    event.owner_id,
                )
                continue
            await mark_reminder_sent(session, event.id)


def register_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    scheduler.add_job(
        _dispatch_due_reminders,
        trigger="interval",
        seconds=60,
        args=[bot],
        id=REMINDER_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Registered calendar reminder job (every 60s)")

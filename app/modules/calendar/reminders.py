"""Event reminder scheduling.

CONTRACT (consumed by app.main):
    def register_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> None
        Register any periodic jobs needed to deliver event reminders.

TODO(subagent-2): scan for due reminders and send them via the bot.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger("calendar.reminders")


def register_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    # Placeholder; subagent-2 adds the interval job that dispatches reminders.
    logger.debug("Calendar reminder jobs not yet registered")

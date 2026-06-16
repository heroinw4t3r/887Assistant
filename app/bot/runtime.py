"""Process-wide runtime singletons (the Bot instance and the scheduler).

Background components (reminders, the web .ics feed) need to reach the Bot
without importing main. They access it through here after startup wires it up.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

_bot: Bot | None = None
_scheduler: AsyncIOScheduler | None = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


def get_bot() -> Bot:
    if _bot is None:
        raise RuntimeError("Bot is not initialised yet")
    return _bot


def set_scheduler(scheduler: AsyncIOScheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> AsyncIOScheduler:
    if _scheduler is None:
        raise RuntimeError("Scheduler is not initialised yet")
    return _scheduler

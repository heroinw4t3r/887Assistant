"""Application entrypoint: wires the bot, routers, scheduler and web server together."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot import errors as errors_router
from app.bot import menu as menu_router
from app.bot import runtime
from app.bot.message_tracking import patch_bot_for_message_tracking
from app.config import get_settings
from app.db.base import init_db
from app.logging_config import setup_logging
from app.modules.ai import handlers as ai_handlers
from app.modules.calendar import handlers as calendar_handlers
from app.modules.calendar import reminders as calendar_reminders
from app.modules.faceit import handlers as faceit_handlers
from app.modules.files import handlers as files_handlers
from app.web.server import start_web_server

logger = logging.getLogger("main")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # Feature routers first, navigation/menu, error handler last.
    dp.include_router(menu_router.router)
    dp.include_router(files_handlers.router)
    dp.include_router(calendar_handlers.router)
    dp.include_router(ai_handlers.router)
    dp.include_router(faceit_handlers.router)
    dp.include_router(errors_router.router)
    return dp


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    await init_db()

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    patch_bot_for_message_tracking(bot)
    runtime.set_bot(bot)

    scheduler = AsyncIOScheduler(timezone="UTC")
    runtime.set_scheduler(scheduler)
    calendar_reminders.register_jobs(scheduler, bot)
    scheduler.start()

    runner = await start_web_server()
    dp = build_dispatcher()

    logger.info("Starting polling…")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

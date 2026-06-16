"""Global error handler so the bot never crashes on a single failing update."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ErrorEvent

logger = logging.getLogger("bot.errors")

router = Router(name="errors")


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    logger.exception("Unhandled error while processing update: %s", event.exception)
    # Try to notify the user without leaking internals.
    update = event.update
    try:
        if update.message:
            await update.message.answer(
                "⚠️ Произошла ошибка. Попробуйте ещё раз или вернитесь в /menu."
            )
        elif update.callback_query:
            await update.callback_query.answer(
                "⚠️ Произошла ошибка, попробуйте ещё раз.", show_alert=True
            )
    except Exception:  # noqa: BLE001 - never let the error handler itself raise
        logger.debug("Failed to notify user about the error", exc_info=True)
    return True

"""aiohttp web server that serves the personal iCalendar (.ics) feeds.

Subscribing to ``<BASE_URL>/calendar/<token>.ics`` (or the ``webcal://`` variant)
in Google Calendar / Apple Calendar gives the user read-only phone sync.
"""
from __future__ import annotations

import logging

from aiohttp import web

from app.config import get_settings

logger = logging.getLogger("web")


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def calendar_feed(request: web.Request) -> web.Response:
    # Imported lazily so the web layer stays decoupled from the calendar module.
    from app.modules.calendar.ics import build_ics_for_token

    token = request.match_info.get("token", "")
    data = await build_ics_for_token(token)
    if data is None:
        raise web.HTTPNotFound(text="Unknown calendar token")
    return web.Response(
        body=data,
        content_type="text/calendar",
        charset="utf-8",
        headers={"Content-Disposition": 'inline; filename="887assistant.ics"'},
    )


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/calendar/{token}.ics", calendar_feed)
    return app


async def start_web_server() -> web.AppRunner:
    settings = get_settings()
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.web_host, settings.web_port)
    await site.start()
    logger.info("Web server listening on %s:%s", settings.web_host, settings.web_port)
    return runner

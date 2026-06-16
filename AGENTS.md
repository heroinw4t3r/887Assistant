# 887Assistant

Multi-tool Telegram bot (aiogram 3) with file storage, calendar (`.ics`/`webcal` feed),
AI chat, and a FACEIT nickname checker. See `README.md` for full feature docs.

## Cursor Cloud specific instructions

The startup update script creates a `.venv` (Python 3.12) and installs `requirements-dev.txt`
(which includes `requirements.txt` + `pytest`, `pytest-asyncio`, `ruff`). Use the interpreter
directly via `.venv/bin/...` (or `source .venv/bin/activate`).

- **Tests:** `.venv/bin/pytest` (config in `pyproject.toml`, `asyncio_mode = auto`). Tests use
  an in-memory/SQLite DB and need no network or secrets.
- **Lint:** `.venv/bin/ruff check .` (use `--fix` to autofix).
- **Run the bot:** `.venv/bin/python -m app.main`. This requires a real `TELEGRAM_BOT_TOKEN`
  in `.env` (copy from `.env.example`); without it the entrypoint exits immediately with a
  "TELEGRAM_BOT_TOKEN is not set" message. Optional feature keys (`LLM_API_KEY`, `FACEIT_API_KEY`)
  are only needed to exercise those specific modules.
- **Calendar web server (`.ics`/`webcal` feed):** served by `app/web/server.py` on
  `WEB_PORT` (default 8080), and is started automatically by `app.main`. The module has no
  `__main__` block, so `python -m app.web.server` is a no-op; to run it standalone call
  `app.web.server.start_web_server()` from an asyncio runner. Endpoints: `GET /health` and
  `GET /calendar/{token}.ics` (404 for unknown tokens).
- **Database:** defaults to SQLite at `./data/887assistant.db` (auto-created by `init_db()`);
  `DATABASE_URL` can point at PostgreSQL via `postgresql+asyncpg://...`. The `data/`, `storage/`,
  `.env`, and `.venv/` paths are gitignored.

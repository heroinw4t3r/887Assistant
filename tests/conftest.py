"""Shared pytest fixtures.

Forces an isolated in-memory-ish SQLite DB for tests before app modules import.
"""
from __future__ import annotations

import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test_887assistant.db")
os.environ.setdefault("FACEIT_API_KEY", "test-faceit-key")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")

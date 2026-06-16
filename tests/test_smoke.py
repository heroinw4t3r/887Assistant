"""Smoke tests: the app imports and the dispatcher builds."""
from __future__ import annotations


def test_import_main():
    from app.main import build_dispatcher

    dp = build_dispatcher()
    assert dp is not None


def test_config_loads():
    from app.config import get_settings

    settings = get_settings()
    assert settings.telegram_bot_token == "test:token"
